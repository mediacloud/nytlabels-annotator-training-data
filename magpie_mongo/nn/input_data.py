import os
import threading

import numpy as np
from gensim.models import Word2Vec
#from keras.models import Graph

from magpie_mongo.base.document import Document
from magpie_mongo.config import BATCH_SIZE, WORD2VEC_MODELPATH, EMBEDDING_SIZE,\
    SCALER_PATH, SAMPLE_LENGTH
from magpie_mongo.utils import get_answers_for_doc, load_from_disk


def get_data_for_model(train_dir, labels, test_dir=None, nn_model=None,
                       as_generator=False, batch_size=BATCH_SIZE,
                       word2vec_model=None, scaler=None):
    """
    Get data in the form of matrices or generators for both train and test sets.
    :param train_dir: directory with train files
    :param labels: an iterable of predefined labels (controlled vocabulary)
    :param test_dir: directory with test files
    :param nn_model: Keras model of the NN
    :param as_generator: flag whether to return a generator or in-memory matrix
    :param batch_size: integer, size of the batch
    :param word2vec_model: trained w2v gensim model
    :param scaler: scaling object for X matrix normalisation e.g. StandardScaler

    :return: tuple with 2 elements for train and test data. Each element can be
    either a pair of matrices (X, y) or their generator
    """

    kwargs = dict(
        label_indices={lab: i for i, lab in enumerate(labels)},
        word2vec_model=word2vec_model or Word2Vec.load(WORD2VEC_MODELPATH),
        scaler=scaler or load_from_disk(SCALER_PATH),
        nn_model=nn_model,
    )

    if as_generator:
        filename_it = FilenameIterator(train_dir, batch_size)
        train_data = iterate_over_batches(filename_it, **kwargs)
    else:
        train_files = {filename[:-4] for filename in os.listdir(train_dir)}
        train_data = build_x_and_y(train_files, train_dir, **kwargs)

    test_data = None
    if test_dir:
        if as_generator:
            test_filename_it = FilenameIterator(test_dir, batch_size)
            test_data = iterate_over_batches(test_filename_it, **kwargs)
        else:
            test_files = {filename[:-4] for filename in os.listdir(test_dir) if filename.endswith('.txt')}
            test_data = build_x_and_y(test_files, test_dir, **kwargs)

    return train_data, test_data

def get_data_for_model_mongo(mongo_collection, train_ids, labels, test_ids=None, nn_model=None,
                       as_generator=False, batch_size=BATCH_SIZE,
                       word2vec_model=None, scaler=None):
    """
    Get data in the form of matrices or generators for both train and test sets.
    :param train_dir: directory with train files
    :param labels: an iterable of predefined labels (controlled vocabulary)
    :param test_dir: directory with test files
    :param nn_model: Keras model of the NN
    :param as_generator: flag whether to return a generator or in-memory matrix
    :param batch_size: integer, size of the batch
    :param word2vec_model: trained w2v gensim model
    :param scaler: scaling object for X matrix normalisation e.g. StandardScaler

    :return: tuple with 2 elements for train and test data. Each element can be
    either a pair of matrices (X, y) or their generator
    """

    kwargs = dict(
        label_indices={lab: i for i, lab in enumerate(labels)},
        word2vec_model=word2vec_model or Word2Vec.load(WORD2VEC_MODELPATH),
        scaler=scaler or load_from_disk(SCALER_PATH),
        nn_model=nn_model,
    )

    if as_generator:
        filename_it = MongoIterator(train_ids, batch_size)
        train_data = iterate_over_batches_mongo(filename_it, mongo_collection, **kwargs)
    else:
        train_data = build_x_and_y_mongo(train_ids, mongo_collection, **kwargs)

    test_data = None
    if test_ids:
        if as_generator:
            test_filename_it = MongoIterator(test_ids, batch_size)
            test_data = iterate_over_batches_mongo(test_filename_it, mongo_collection, **kwargs)
        else:
            test_data = build_x_and_y_mongo(test_ids, mongo_collection, **kwargs)

    return train_data, test_data


def build_x_and_y(filenames, file_directory, **kwargs):
    """
    Given file names and their directory, build (X, y) data matrices
    :param filenames: iterable of strings showing file ids (no extension)
    :param file_directory: path to a directory where those files lie
    :param kwargs: additional necessary data for matrix building e.g. scaler

    :return: a tuple (X, y)
    """
    label_indices = kwargs['label_indices']
    word2vec_model = kwargs['word2vec_model']
    scaler = kwargs['scaler']
    nn_model = kwargs['nn_model']

    x_matrix = np.zeros((len(filenames), SAMPLE_LENGTH, EMBEDDING_SIZE))
    y_matrix = np.zeros((len(filenames), len(label_indices)), dtype=np.bool_)

    for doc_id, fname in enumerate(filenames):
        doc = Document(doc_id, os.path.join(file_directory, fname + '.txt'))
        words = doc.get_all_words()[:SAMPLE_LENGTH]

        for i, w in enumerate(words):
            if w in word2vec_model:
                word_vector = word2vec_model[w].reshape(1, -1)
                x_matrix[doc_id][i] = scaler.transform(word_vector, copy=True)[0]

        labels = get_answers_for_doc(
            fname + '.txt',
            file_directory,
            filtered_by=set(label_indices.keys()),
        )

        for lab in labels:
            index = label_indices[lab]
            y_matrix[doc_id][index] = True

    if nn_model and type(nn_model.input) == list:
        return_data = [x_matrix] * len(nn_model.input), y_matrix
    else:
        return_data = [x_matrix], y_matrix

    # if type(nn_model) == Graph:
    #     return {'input': return_data[0], 'output': return_data[1]}
    # else:
    return return_data

def build_x_and_y_mongo(ids, mongo_collection, **kwargs):
    """
    Given file names and their directory, build (X, y) data matrices
    :param filenames: iterable of strings showing file ids (no extension)
    :param file_directory: path to a directory where those files lie
    :param kwargs: additional necessary data for matrix building e.g. scaler

    :return: a tuple (X, y)
    """
    label_indices = kwargs['label_indices']
    word2vec_model = kwargs['word2vec_model']
    scaler = kwargs['scaler']
    nn_model = kwargs['nn_model']

    x_matrix = np.zeros((len(ids), SAMPLE_LENGTH, EMBEDDING_SIZE))
    y_matrix = np.zeros((len(ids), len(label_indices)), dtype=np.bool_)

    docs = mongo_collection.find({"_id":{"$in":ids}})

    for doc_id, d in enumerate(docs):
        #doc_id = d["_id"]
        doc = Document(doc_id, None, text=d["full_text"])
        words = doc.get_all_words()[:SAMPLE_LENGTH]

        for i, w in enumerate(words):
            if w in word2vec_model:
                word_vector = word2vec_model[w].reshape(1, -1)
                x_matrix[doc_id][i] = scaler.transform(word_vector, copy=True)[0]

        #d_labels = set([label.lower() for label in (d["general_online_descriptors"] + d["descriptors"] + d["online_descriptors"]+ d["taxonomic_classifiers"])])
        d_labels = set([label for label in d["taxonomic_classifiers"]])
        labels=[]
        if len(d_labels)>0:
            labels = get_answers_for_doc(
                None,
                None,
                labels_arr=d_labels,
                filtered_by=set(label_indices.keys()),
            )
        for lab in labels:
            index = label_indices[lab]
            y_matrix[doc_id][index] = True

    if nn_model and type(nn_model.input) == list:
        return_data = [x_matrix] * len(nn_model.input), y_matrix
    else:
        return_data = [x_matrix], y_matrix

    # if type(nn_model) == Graph:
    #     return {'input': return_data[0], 'output': return_data[1]}
    # else:
    return return_data


def iterate_over_batches(filename_it, **kwargs):
    """
    Iterate infinitely over a given filename iterator
    :param filename_it: FilenameIterator object
    :param kwargs: additional necessary data for matrix building e.g. scaler
    :return: yields tuples (X, y) when called
    """
    while True:
        files = filename_it.next()
        yield build_x_and_y(files, filename_it.dirname, **kwargs)

def iterate_over_batches_mongo(filename_it, mongo_collection, **kwargs):
    """
    Iterate infinitely over a given filename iterator
    :param filename_it: FilenameIterator object
    :param kwargs: additional necessary data for matrix building e.g. scaler
    :return: yields tuples (X, y) when called
    """
    while True:
        ids = filename_it.next()
        yield build_x_and_y_mongo(ids, mongo_collection, **kwargs)

class MongoIterator(object):
    """ A threadsafe iterator yielding a fixed number of filenames from a given
     folder and looping forever. Can be used for external memory training. """
    def __init__(self, ids, batch_size):
        self.batch_size = batch_size
        self.lock = threading.Lock()
        self.ids = ids
        self.i = 0

    def __iter__(self):
        return self

    def next(self):
        with self.lock:

            if self.i == len(self.ids):
                self.i = 0

            batch = self.ids[self.i:self.i + self.batch_size]
            if len(batch) < self.batch_size:
                self.i = 0
            else:
                self.i += self.batch_size

            return batch

class FilenameIterator(object):
    """ A threadsafe iterator yielding a fixed number of filenames from a given
     folder and looping forever. Can be used for external memory training. """
    def __init__(self, dirname, batch_size):
        self.dirname = dirname
        self.batch_size = batch_size
        self.lock = threading.Lock()
        self.files = list({filename[:-4] for filename in os.listdir(dirname) if filename.endswith('.txt')})
        self.i = 0

    def __iter__(self):
        return self

    def next(self):
        with self.lock:

            if self.i == len(self.files):
                self.i = 0

            batch = self.files[self.i:self.i + self.batch_size]
            if len(batch) < self.batch_size:
                self.i = 0
            else:
                self.i += self.batch_size

            return batch
