
import time
import yaml
import logging
from datetime import datetime

from pie.settings import settings_from_file
from pie.trainer import Trainer
from pie.data import Dataset, Reader, MultiLabelEncoder
from pie.models import SimpleModel

# set seeds
import random
import numpy
import torch

seed = 1001
random.seed(seed)
numpy.random.seed(seed)
torch.manual_seed(seed)
if torch.cuda.is_available():
    torch.cuda.manual_seed(seed)


def get_fname_infix(settings):
    # fname
    fname = os.path.join(settings.modelpath, settings.modelname),
    # infix
    targets = [t['name'] for t in settings.tasks if t.get('schedule', {}).get('target')]
    timestamp = datetime.now().strftime("%Y_%m_%d-%H_%M_%S")
    infix = '-'.join(['+'.join(targets), timestamp])

    return fname, infix


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('config_path', nargs='?', default='config.json')
    args = parser.parse_args()

    settings = settings_from_file(args.config_path)

    # datasets
    reader = Reader(settings, input_path=settings.input_path)
    tasks = reader.check_tasks(expected=None)
    label_encoder = MultiLabelEncoder.from_settings(settings, tasks=tasks)
    if settings.verbose:
        print("::: Available tasks :::")
        print()
        for task in tasks:
            print("- {}".format(task))
        print()

    # fit
    start = time.time()
    if settings.verbose:
        print("::: Fitting data :::")
        print()
    ninsts = label_encoder.fit_reader(reader)
    if settings.verbose:
        print("Found {} total instances in training set in {:g} secs".format(
            ninsts, time.time() - start))
        print()
        print("::: Vocabulary :::")
        print()
        print("- {:<15} vocab={:<6}".format("word", len(label_encoder.word)))
        print("- {:<15} vocab={:<6}".format("char", len(label_encoder.char)))
        print()
        print("::: Target tasks :::")
        print()
        for task, le in label_encoder.tasks.items():
            print("- {:<15} target={:<6} level={:<6} vocab={:<6}"
                  .format(task, le.target, le.level, len(le)))
        print()

    trainset = Dataset(settings, reader, label_encoder)

    devset = None
    if settings.dev_path is not None:
        devset = Dataset(
            settings, Reader(settings, settings.dev_path), label_encoder=label_encoder
        ).batch_generator()
    elif settings.dev_split > 0:
        devset = trainset.get_dev_split(ninsts, split=settings.dev_split)
        ninsts = ninsts - (len(devset) * settings.batch_size)
    else:
        logging.warning("No devset: cannot monitor/optimize training")

    testset = None
    if settings.test_path is not None:
        testset = Dataset(settings, Reader(settings, settings.test_path), label_encoder)

    # model
    model = SimpleModel(trainset.label_encoder,
                        settings.wemb_dim, settings.cemb_dim, settings.hidden_size,
                        settings.num_layers, dropout=settings.dropout,
                        cemb_type=settings.cemb_type,
                        include_self=settings.include_self, pos_crf=True)
    model.to(settings.device)

    print("::: Model :::")
    print()
    print(model)
    print()
    print("::: Model parameters :::")
    print()
    print(sum(p.nelement() for p in model.parameters()))
    print()

    # training
    print("Starting training")
    trainer = Trainer(settings, model, trainset, ninsts)
    try:
        trainer.train_epochs(settings.epochs, dev=devset)
    except KeyboardInterrupt:
        print("Stopping training")
    finally:
        if testset is not None:
            print("Evaluating model on test set")
            model.eval()
            test_scores = model.evaluate(testset.batch_generator())
            print()
            print("::: Test scores :::")
            print()
            print(yaml.dump(test_scores, default_flow_style=False))
            print()

        # save model
        fpath, infix = get_fname_infix(settings)
        fpath = model.save(fpath, infix=infix)
        print("Saved best model to: [{}]".format(fpath))

    print("Bye!")
