import os
from sqlalchemy import create_engine, Column, Float, Integer, String, DateTime
from sqlalchemy.orm import sessionmaker
import datetime
from Fireworks import Message
from Fireworks import database as db

"""
This module contains classes and functions for saving and loading data collected during experiments.
"""

metadata_columns = [
    Column('name', String),
    Column('iteration', Integer),
    Column('description', String),
    Column('timestamp', DateTime),
]
metadata_table = db.create_table('metadata', columns=metadata_columns)

def load_experiment(experiment_path): # TODO: clean up attribute assignments for loading
    """
    Returns an experiment object corresponding to the database in the given path.
    """
    experiment_name = experiment_path.split('/')[-1]
    db_path = '/'.join(experiment_path.split('/')[:-1])
    return Experiment(experiment_name, db_path, load=True)

class Experiment:
    # NOTE: For now, we assume that the underlying database is sqlite on local disk
    # QUESTION: Should we implement an __eq__ method for experiments?
    # TODO: Expand to support nonlocal databases

    def __init__(self, experiment_name, db_path, description=None, load=False):

        self.name = experiment_name
        self.db_path = db_path
        self.description = description or ''
        self.timestamp = datetime.datetime.now() # QUESTION: Should this be updated on each load?
        self.engines = {}
        if load:
            self.load_experiment()
            self.engines = {
                name.rstrip('.sqlite'): self.create_engine(name.rstrip('.sqlite'))
                for name in os.listdir(self.save_path) if name.endswith('.sqlite')
                }
            self.load_metadata()
        else:
            self.create_dir()
            self.init_metadata()

        self.filenames = os.listdir(os.path.join(self.db_path,self.save_path)) # Refresh list of filenames
        # Create/open save directory
        # if not os.path.exists(save_dir):
        #     try:
        #         os.makedirs(save_dir)
        #     except Error as e:
        #         print("Could not create save directory {save_dir}. Please check permissions and try again: {error}".format(save_dir=save_dir, error=e))
        # self.save_dir = save_dir

    def load_experiment(self, path=None, experiment_name=None):
        """
        Loads in parameters associated with this experiment from a directory.
        """
        path = path or self.db_path
        experiment_name = experiment_name or self.name
        self.save_path = os.path.join(path, experiment_name)
        if not experiment_name in os.listdir(path):
            raise ValueError("Directory {exp_dir} was not found in {path}".format(exp_dir=experiment_name, path=path))
        self.engine = create_engine("sqlite:///{save_path}".format(save_path=os.path.join(self.save_path,'metadata.sqlite')))

    def create_dir(self):
        """
        Creates a folder in db_path directory corresponding to this Experiment.
        """
        dirs = os.listdir(self.db_path)
        previous_experiments = [d for d in dirs if d.startswith(self.name)]
        self.iteration = len(previous_experiments)
        os.makedirs(os.path.join(self.db_path, "{name}_{iteration}".format(name=self.name, iteration=self.iteration))) # TODO: Upgrade to 3.6 and use f-strings
        self.save_path = "{name}_{iteration}".format(name=self.name, iteration=self.iteration)
        self.engine = create_engine("sqlite:///{save_path}".format(save_path=os.path.join(self.db_path,self.save_path,'metadata.sqlite')))

    def load_metadata(self):
        self.metadata = db.TableSource(metadata_table, self.engine, columns=['name', 'iteration', 'description', 'timestamp'])
        # Session = sessionmaker(bind=self.engine)
        # session = Session()
        # assert False
        metadata = self.metadata.session.query(metadata_table).one()
        self.name = metadata.name
        self.iteration = metadata.iteration
        self.description = metadata.description
        self.timestamp = metadata.timestamp

    def init_metadata(self):

        self.metadata = db.TableSource(metadata_table, self.engine, columns=['name', 'iteration', 'description', 'timestamp'])
        self.metadata.insert(Message({'name': [self.name], 'iteration': [self.iteration], 'description': [self.description], 'timestamp': [self.timestamp]}))
        self.metadata.commit()

    def create_engine(self, name):
        """
        Creates an engine corresponding to a database with the given name. In particular, this creates a file called {name}.sqlite
        in this experiment's save directory, and makes an engine to connect to it.
        """
        if name in self.engines:
            raise ValueError("Engine with name {name} already exists in this experiment.".format(name=name))
        self.engines[name] = create_engine("sqlite:///{filename}".format(filename=os.path.join(self.db_path,self.save_path, name+'.sqlite')))
        return self.engines[name]

    def get_session(self, name):
        """
        Creates an SQLalchemy session corresponding to the engine with the given name that can be used to interact with the database.
        """
        if name in self.engines:
            engine = self.engines[name]
        else: # QUESTION: Should this raise an error or autocreate a new engine?
            engine = self.create_engine(name)
        Session = sessionmaker(bind=engine)
        session = Session()
        return session

    def open(self, filename, *args, string_only=False):
        """
        Returns a handle to a file with the given filename inside this experiment's directory.
        If string_only is true, then this instead returns a string with the path to create the file.
        If the a file with 'filename' is already present in the directory, this will raise an error.
        """
        self.filenames = os.listdir(os.path.join(self.db_path,self.save_path)) # Refresh list of filenames
        # if filename in self.filenames:
        #     raise IOError("A file named {filename} already exists in this experiments directory ({directory})".format(filename=filename, directory=self.save_path))
        path = os.path.join(self.db_path,self.save_path, filename)
        if string_only:
            return path
        else:
            return open(path, *args)
        self.filenames = os.listdir(os.path.join(self.db_path,self.save_path)) # Refresh list of filenames

def filter_columns(message, columns = None):
    """
    Returns only the given columns of message or everything if columns is None.
    If tensor columns are requested, they are converted to ndarray first.
    """
    return message # TODO: Implement
