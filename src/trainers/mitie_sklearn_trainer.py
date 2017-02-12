from mitie import *
import cloudpickle
import datetime
import os

from rasa_nlu.classifiers.sklearn_intent_classifier import SklearnIntentClassifier
from rasa_nlu.featurizers.mitie_featurizer import MITIEFeaturizer
from rasa_nlu.trainers.trainer import Trainer
from training_utils import write_training_metadata


class MITIESklearnTrainer(Trainer):
    SUPPORTED_LANGUAGES = {"en"}

    def __init__(self, fe_file, language_name):
        self.name = "mitie_sklearn"
        self.training_data = None
        self.intent_classifier = None
        self.entity_extractor = None
        self.training_data = None
        self.fe_file = fe_file
        self.featurizer = MITIEFeaturizer(self.fe_file)
        self.ensure_language_support(language_name)

    def train(self, data):
        self.training_data = data
        self.intent_classifier = self.train_intent_classifier(data.intent_examples)
        self.entity_extractor = self.train_entity_extractor(data.entity_examples)

    def start_and_end(self, text_tokens, entity_tokens):
        size = len(entity_tokens)
        max_loc = 1 + len(text_tokens) - size
        locs = [i for i in range(max_loc) if text_tokens[i:i + size] == entity_tokens]
        start, end = locs[0], locs[0] + len(entity_tokens)
        return start, end

    def train_entity_extractor(self, entity_examples):
        trainer = ner_trainer(self.fe_file)
        for example in entity_examples:
            tokens = tokenize(example["text"])
            sample = ner_training_instance(tokens)
            for ent in example["entities"]:
                _slice = example["text"][ent["start"]:ent["end"] + 1]
                val_tokens = tokenize(_slice)
                start, end = self.start_and_end(tokens, val_tokens)
                sample.add_entity(xrange(start, end), ent["entity"])
            trainer.add(sample)

        ner = trainer.train()
        return ner

    def train_intent_classifier(self, intent_examples, test_split_size=0.1):
        intent_classifier = SklearnIntentClassifier()
        labels = [e["intent"] for e in intent_examples]
        sentences = [e["text"] for e in intent_examples]
        y = intent_classifier.transform_labels_str2num(labels)
        X = self.featurizer.create_bow_vecs(sentences)
        intent_classifier.train(X, y, test_split_size)
        return intent_classifier

    def persist(self, path, persistor=None, create_unique_subfolder=True):
        timestamp = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')

        if create_unique_subfolder:
            dir_name = os.path.join(path, "model_" + timestamp)
            os.mkdir(dir_name)
        else:
            dir_name = path

        data_file = os.path.join(dir_name, "training_data.json")
        classifier_file, ner_dir = None, None
        if self.intent_classifier:
            classifier_file = os.path.join(dir_name, "intent_classifier.pkl")
        if self.entity_extractor:
            entity_extractor_file = os.path.join(dir_name, "entity_extractor.dat")

        write_training_metadata(dir_name, timestamp, data_file, self.name, 'en',
                                classifier_file, entity_extractor_file, self.fe_file)

        with open(data_file, 'w') as f:
            f.write(self.training_data.as_json(indent=2))
        if self.entity_extractor:
            self.entity_extractor.save_to_disk(entity_extractor_file)
        if self.intent_classifier:
            with open(classifier_file, 'wb') as f:
                cloudpickle.dump(self.intent_classifier, f)

        if persistor is not None:
            persistor.send_tar_to_s3(dir_name)
