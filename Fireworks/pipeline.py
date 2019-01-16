from abc import ABC, abstractmethod
from Bio import SeqIO
import pandas as pd
import Fireworks
from Fireworks.message import Message
from Fireworks.utils import index_to_list
from Fireworks.cache import LRUCache, LFUCache, UnlimitedCache
from Fireworks.preprocessing import one_hot
from abc import ABC, abstractmethod
from itertools import count
import types
import random
from bidict import bidict
import torch
import math
import numpy as np

class Pipe(ABC):
    """
    The core data structure in fireworks.
    A Pipe can take Pipes as inputs, and its outputs can be streamed to other Pipes.
    All communication is done via Message objects.
    Method calls are deferred to input Pipes recursively until a Pipe that implements the method is reached.

    This is made possible with a recursive function call method. Any Pipe can use this method to call a method on its inputs; this will recursively loop until reaching a Pipe that implements the method and return those outputs (as a Message) or raise an error if there are none. For example, we can do something like this:

    ::

        reader = pipe_for_reading_from_some_dataset(...)
        cache = CachingPipe(input_pipes = {'reader': reader}, type='LRU')
        embedder = CreateEmbeddingsPipe(input_pipes = {'data': cache})
        loader = CreateMinibatchesPipe(input_pipes = {'data': embedder})

        loader.reset()
        for batch in loader:
        	# Code for training

    Under the hood, the code for loader.__next__() can choose to recursively call a to_tensor() method which is implemented by embedder. Index queries and other magic methods can also be implemented recursively, and this enables a degree of commutativity when stacking Pipes together (changing the order of Pipes is often allowed because of the pass-through nature of recursive calls).

    Note that in order for this to work well, there must be some consistency among method names. If a Pipe expects ‘to_tensor’ to convert batches to tensor format, then an upstream Pipe must have a method with that name, and this should remain consistent across projects to maintain reusability. Lastly, the format for specifying inputs to a Pipe is a dictionary of Pipes. The keys in this dictionary can provide information for the Pipe to use or be ignored completely.

    """

    name = 'base_pipe'

    def __init__(self, input_pipe = None, *args, **kwargs):

        # if type(input_pipe) is dict:
        #     if len(input_pipe.keys()) > 1:
        #         raise TypeError("Input must be a single Pipe.")
        if isinstance(input_pipe, Pipe): # Can give just one Pipe as input without having to type out an entire dict
            # input_pipe = {'data': input_pipe}
            self.input_pipe = input_pipe
        elif input_pipe is None: # Subclasses can have their own method for creating an inputs_dict and just leave this argument blank
            self.input_pipe = None
        else:
            raise TypeError("Inputs must be a Pipe")
        # for title, pipe in input_pipe.items(): # There is only one
        #     self.input_title = title
        #     self.input_pipe = pipe
        # self.check_inputs()

     # def check_inputs(self):
     #    if len(self.input_pipes) > 1:
     #        raise ValueError("A pass-through Pipe can only have one input Pipe.")

    def __getitem__(self, *args, **kwargs):
        return self.input_pipe.__getitem__(*args, **kwargs)

    def __setitem__(self, *args, **kwargs):
        return self.input_pipe.__setitem__(*args, **kwargs)

    def __delitem__(self, *args, **kwargs):
        return self.input_pipe.__delitem__(*args, **kwargs)

    def __len__(self, *args, **kwargs):
        return self.input_pipe.__len__(*args, **kwargs)

    def __next__(self, *args, **kwargs):
        return self.input_pipe.__next__(*args, **kwargs)

    def __iter__(self, *args, **kwargs):
        return self.input_pipe.__iter__(*args, **kwargs)

    def __getattr__(self, *args, **kwargs):
        """
        Pass through all methods of the input Pipe while adding labels. This does not intercept special methods (__x__ methods)
        """
        return self.recursive_call(*args, **kwargs) #self.input_pipe.__getattribute__(*args, **kwargs)

    def recursive_call(self, attribute, *args, ignore_first = True, **kwargs):
        """
        Recursively calls method/attribute on input_pipes until reaching an upstream Pipe that implements the method and
        returns the response as a message (empty if response is None).
        Recursive calls enable a stack of Pipes to behave as one entity; any method implemented by any component can be accessed
        recursively.

        Args:
            attribute: The name of the attribute/method to call.
            args: The arguments if this is a recursive method call.
            ignore_first: If True, then ignore whether or not the target attribute is implemented by self. This can be useful if a Pipe
                implements a method and wants to use an upstream call of the same method as well.
            kwargs: The kwargs is this is a recursive method call.

        Returns:
            Responses (dict): A dictionary mapping the name of each input Pipe to the response that was returned.
        """

        if not ignore_first:
            if hasattr(self, attribute):
                if args or kwargs: # Is a method call
                    return self.__getattribute__(attribute)(*args,**kwargs)

                else: # Is an attribute
                    try:
                        return self.__getattribute__(attribute)
                    except AttributeError:
                        return self.__getattr__(attribute)

        if not self.input_pipes:
            raise AttributeError("Pipe {0} does not have method/attribute {1}.".format(self.name, str(attribute)))

        responses = [pipe.recursive_call(attribute, *args, ignore_first=False, **kwargs) for pipe in self.input_pipes.values()]

        if responses:
            if isinstance(responses[0], Pipe):
                return Fireworks.merge(responses)
            elif len(responses) == 1:
                return responses[0]
            else:
                return {key: response for key, respone in zip(self.input_pipes.keys(), responses)}

class PassThroughPipe(Pipe):
    """
    This Pipe passes through data access calls and methods to its (single) input Pipe except for whatever is overridden by subclasses.
    NOTE: Only the special methods explicitly defined here (getitem, len, delitem, setitem, next, iter) are passed through.
    Non-special methods are passed through normally.
    """

    # TODO: Make every Pipe passthrough.
    name = 'Passthrough Pipe'

class HookedPassThroughPipe(Pipe): # BUG NOTE: Methods that return self will break the passthrough at the moment
    """
    This Pipe has hooks which can be implemented by subclasses to modify the behavior of
    passed through calls.
    """

    name = 'Hooked-passthrough Pipe'

    def _getitem_hook(self, message): return message

    # def _setitem_hook(self, *args, **kwargs): pass
    #
    # def _delitem_hook(self, *args, **kwargs): pass
    #
    # def _len_hook(self, *args, **kwargs): return args[0]

    def _next_hook(self, message): return message

    # def _iter_hook(self, *args, **kwargs): return args[0]

    def __getitem__(self, *args, **kwargs): # TODO: wrap access methods in try/catch statements

        return self._getitem_hook(Message(self.input_pipe.__getitem__(*args, **kwargs))) #self.input_pipe.__getitem__(*args, **kwargs))

    # def __setitem__(self, *args, **kwargs):
    #     self._setitem_hook(self.input_pipe.__setitem__(*args, **kwargs))
    #
    # def __delitem__(self, *args, **kwargs):
    #     self._delitem_hook(self.input_pipe.__delitem__(*args, **kwargs))
    #
    # def __len__(self, *args, **kwargs):
    #     return self._len_hook(self.input_pipe.__len__(*args, **kwargs))

    def __next__(self, *args, **kwargs):
        return self._next_hook(Message(self.input_pipe.__next__(*args, **kwargs)))

    def __iter__(self, *args, **kwargs):

        self.input_pipe = self.input_pipe.__iter__(*args, **kwargs)
        return self

    # def __getattr__(self, *args, **kwargs):
    #     """
    #     Pass through all methods of the input Pipe while adding labels. This does not intercept special methods (__x__ methods)
    #     """
    #     return self.input_pipe.__getattribute__(*args, **kwargs)

class BioSeqPipe(Pipe):
    """
    Class for representing biosequence data.
    Specifically, this class can read biological data files (such as fasta) and iterate throug them as a Pipe.
    This can serve as the first Pipe in a pipeline for analyzing genomic data.
    """

    name = 'BioSeqPipe'

    def __init__(self, path, inputs = None, filetype = 'fasta', **kwargs):
        """
        Args:
            path: Path on disk where file is located; will be supplied to the SeqIO.parse function.
            inputs: Input Pipes. Default is None.
            filetype: Type of file that will be supplied to the SeqIO.parse function. Default is 'fasta'
            kwargs: Optional key word arguments that will be supplied to the SeqIO.parse function.
        """
        self.path = path
        self.filetype = filetype
        self.kwargs = kwargs
        self.seq = SeqIO.parse(self.path, self.filetype, **self.kwargs)
        self.input_pipes = {}

    def reset(self):
        """
        Resets the iterator to the beginning of the file. Specifically, it calls SeqIO.parse again as if reinstantiating the object.
        """
        self.seq = SeqIO.parse(self.path, self.filetype, **self.kwargs)
        return self

    def __next__(self):
        """
        Each iteration through a SeqIO object will produce a named tuple. This Pipe converts that tuple to a Message and produces the result.
        """
        gene = self.seq.__next__()

        try:
            return Message({
                'sequences': [str(gene.seq)],
                'ids': [gene.id],
                'names': [gene.name],
                'descriptions': [gene.description],
                'dbxrefs': [gene.dbxrefs],
            })
        except StopIteration:
            raise StopIteration

    def __iter__(self):
        return self.reset()

class LoopingPipe(Pipe):
    """
    This Pipe can take any iterator and make it appear to be indexable by iterating through the input
    as needed to reach any given index.

    The input Pipe must implement __next__ and reset (to be repeatable),
    and this will simulate __getitem__ by repeatedly looping through the iterator as needed.

    For example, say we have a Pipe that iterates through the lines of a FASTA file:
    ::

        fasta = BioSeqPipe('genes.fasta')

    This Pipe can only iterate through the file in one direciton. If we want to access arbitrary elements,
    we can do this:
    ::

        clock = LoopingPipe(inputs=fasta)
        clock[10]
        clock[2:6]
        len(clock)

    All of these actions are now possible. Note that this is in general an expensive process, because the Pipe
    has to iterate one at a time to get to the index it needs. In practice, this Pipe should pipe its output
    to a CachingPipe that can store values in memory. This approach enables you to process datasets that don't
    entirely fit in memory; you can stream in what you need and cache portions. From the perspective of the downstream
    Pipes, every element of the dataset is accessible as if it were in memory.

    """

    name = 'LoopingPipe'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_inputs()
        self.reset()
        self.length = None

    def __getitem__(self, index):
        """
        Retreives items in index by looping through inputs as many times as needed.
        """

        # TODO: Check if index exceeds length, either explicitly or implicitly.

        # Sort index
        index = sorted(index_to_list(index))
        above = [i for i in index if i >= self.position] # Go forward to reach these
        below = [i for i in index if i < self.position] # Will have to reset the loop to reach these
        if len(above) > 0:
            above_values = Fireworks.cat([self.step_forward(i+1) for i in above])
        else:
            above_values = Message()
        if len(below) > 0:
            self.reset() # Position will now be reset to 0
            below_values = Fireworks.cat([self.step_forward(i+1) for i in below])
        else:
            below_values = Message()
        return below_values.append(above_values) # TODO: Resort this message so values are in the order requested by index

    def __len__(self):
        """
        Length is also calculated implicitly as items are accessed.
        """
        if self.length is not None:
            return self.length
        else:
            self.compute_length()
            return self.length

    def __next__(self): # QUESTION: Should __next__ calls be supported for this Pipe?
        """
        Go forward one step. This can be used to loop over the inputs while automatically recording
        length once one cycle has been performed.
        """
        if self.length is None:
            return self.step_forward(1)
        else:
            p = (self.position + 1) % self.length
            self.position = p
            return self[p]

    def check_inputs(self):
        """
        Checks inputs to determine if they implement __next__ and reset methods.
        """
        for name, pipe in self.input_pipes.items():
            if not (hasattr(pipe, '__next__') and hasattr(pipe, 'reset')):
                raise TypeError('Pipe {0} does not have __next__ and reset methods.'.format(name))

    def reset(self):
        """
        Calls reset on input Pipes and sets position to 0.
        """
        for pipe in self.input_pipes.values():
            pipe.reset()
        self.position = 0

    def compute_length(self):
        """
        Step forward as far as the inputs will allow and compute length.

        Length is also calculated implicitly as items are accessed.

        Note: If the inputs are infinite, then this will go on forever.
        """
        while True:
            try:
                self.step_forward(self.position+1)
            except (StopIteration, IndexError):
                self.reset()
                break

    def step_forward(self, n):
        """
        Steps forward through inputs until position = n and then returns that value.

        This also updates the internal length variable if the iterator ends due to this method call.
        """
        if self.length is not None and n > self.length:
            raise IndexError("Requested index is out of bounds for inputs with length {0}.".format(self.length))
        if n < self.position:
            raise IndexError("Can only step forward to a value higher than current position.")
        x = Message()
        for _ in range(n - self.position):
            try:
                # x = x.append(Fireworks.merge([Pipe.__next__() for Pipe in self.input_pipes.values()]))
                x = Fireworks.merge([pipe.__next__() for pipe in self.input_pipes.values()])
                self.position += 1
            except StopIteration:
                self.length = self.position
                raise IndexError("Requested index is out of bounds for inputs with length {0}.".format(self.length))
        return x

class CachingPipe(Pipe):
    """
    This Pipe can be used to dynamically cache elements from upstream Pipes.
    Whenever data is requested by index, this Pipe will intercept the request and add that message alongside
    the index to its internal cache.
    This can be useful for dealing with datasets that don't fit in memory or are streamed in. You can cache portions
    of the dataset as you use them. By combining this with a LoopingPipe, you can create the illusion of making
    the entire dataset available to downstream Pipes regardless of the type and size of the original data.

    More specifically, fiven input Pipes that implement __getitem__, will store all calls to __getitem__ into
    an internal cache and therafter __getitem__ calls will either access from the cache or trigger __getitem__ calls
    on the input and an update to the cache.

    For example,

    ::

        fasta = BioSeqPipe(path='genes.fasta')
        clock = LoopingPipe(inputs=fasta)
        cache = CachingPipe(inputs=clock, cache_size=100) # cache_size is optional; default=100

    Will set up a pipeline that reads lines from a FASTA file and acessess and caches elements as requests are made

    ::

        cache[20:40] # This will be cached
        cache[25:30] # This will read from the cache
        cache[44] # This will update the cache
        cache[40:140] # This will fill the cache, flushing out old elements
        cache[25:30] # This will read from the dataset and update the cache again

    """
    def __init__(self, *args, cache_size = 100, buffer_size = 0, cache_type = 'LRU', infinite = False, **kwargs):
        """
        Args:
            args: Positional arguments for superclass initialization.
            cache_size (int): Number of elements to hold in cache. Default = 100
            buffer_size (int): Number of elements to clear once cache is full. This is useful if you expect frequent cache misses and
                don't expect to reuse previous cached elements. Default = 0
            cache_type (str): Type of cache. Choices are 'LRU' (least-recently-used) and 'LFU' (least-frequently-used). Default = 'LRU'
            infinite (bool): If set to true, the cache will have no upper limit on size and will never clear itself.
        """
        super().__init__(*args, **kwargs)
        self.check_inputs()
        self.length = None
        self.lower_bound = 0
        self.upper_bound = None
        self.infinite = infinite
        self.cache_size = cache_size
        self.cache_type = cache_type
        self.buffer_size = buffer_size
        self.init_cache(*args, **kwargs)

    # @abstractmethod # TODO: Make different types of caches implementable via subclasses
    def init_cache(self, *args, **kwargs):
        """
        This should initialize a cache object called self.cache
        """
        choices = {'LRU': LRUCache, 'LFU': LFUCache}
        self.cache = choices[self.cache_type](max_size = self.cache_size, buffer_size=self.buffer_size)

    def check_inputs(self):
        """
        Checks inputs to determine if they implement __getitem__.
        """
        for name, pipe in self.input_pipes.items():
            if not (hasattr(pipe, '__getitem__')):
                raise TypeError('Pipe {0} does not have __getitem__ method.'.format(name))

    def __getitem__(self, index):

        index = index_to_list(index)
        if self.length and len(index): # Implicit length check if length is known
            if max(index) >= self.length:
                raise IndexError("Requested index is out of bounds for inputs with length {0}.".format(self.length))
        # Identify what is in the cache and what isn't.
        in_cache = [i for i in index if i in self.cache.pointers] # Elements of index corresponding to in_cache elements
        in_cache_indices = [j for i,j in zip(index, count()) if i in self.cache.pointers] # Indices in index corresponding to in_cache elements
        not_in_cache = [i for i in index if i not in self.cache.pointers] # Elements of index corresponding to not_in_cache elements
        not_in_cache_indices = [j for i,j in zip(index, count()) if i not in self.cache.pointers] # Indices in index corresponding to not_in_cache elements

        # Retrieve from cache existing elements
        in_cache_elements = self.cache[in_cache] # elements in cache corresponding to indices in cache
        # Update cache to have other elements
        not_in_cache_elements = Fireworks.merge([pipe[not_in_cache] for pipe in self.input_pipes.values()])
        self.cache[not_in_cache] = not_in_cache_elements
        # Reorder and merge requested elements
        message = in_cache_elements.append(not_in_cache_elements)
        indices = in_cache_indices
        indices.extend(not_in_cache_indices)
        # Elements must be reordered based on their order in index
        permutation = indices.copy()
        for i,j in zip(indices, count()):
            permutation[i] = j
        # permutation = in_cache_indices.extend(not_in_cache_indices)
        message = message.permute(permutation)

        # Implicit update of internal knowledge of length
        if len(index) and self.length is None and not self.infinite:
            l = max(index)
            if l > self.lower_bound:
                self.lower_bound = l

        return message

    def __len__(self):
        """
        Length is computed implicitly and lazily. If any operation causes the Pipe
        to reach the end of it's inputs, that position is stored as the length.
        Alternatively, if this method is called before that happens, the Pipe will attempt to
        loop to the end and calculate the length.
        """
        if self.infinite:
            raise ValueError("Pipe is labelled as having infinite length (ie. yields items indefinitely).")
        elif self.length is None:
            self.compute_length()
            return self.length
        else:
            return self.length

    def compute_length(self):
        """
        Step forward as far as the inputs will allow and compute length.
        Note: If the inputs are infinite, then this will go on forever.
        """
        if not self.infinite:
            while True:
                try:
                    self[1 + self.lower_bound] # Use knowledge of lower bound from previous getitem calls to accelerate this process
                except IndexError:
                    self.length = 1 + self.lower_bound
                    break
        else:
            raise ValueError("Pipe is labelled as having infinite length (ie. yields items indefinitely).")



class Title2LabelPipe(HookedPassThroughPipe):
    """
    This Pipe takes one Pipe as input and inserts a column called 'label' containing the name
    of the input Pipe to to all outputs.
    """

    def __init__(self, *args, labels_column = 'labels', **kwargs):

        super().__init__(*args, **kwargs)
        self.labels_column = labels_column
        self.check_inputs()

    def check_inputs(self):
        if len(self.input_pipes) > 1:
            raise ValueError("A label Pipe can only have one input Pipe.")
        for label, pipe in self.input_pipes.items(): # There is only one
            self.label = label
            self.input_pipe = pipe

    def _get_item_hook(self, message):

        return self.insert_labels(message)

    def _next_hook(self, message):

        return self.insert_labels(message)

    # def __getattr__(self, *args, **kwargs):
    #     """
    #     Pass through all methods of the input pipe while adding labels.
    #     """
    #     output = self.input_pipe.__getattribute__(*args, **kwargs)
    #     if type(output) is types.MethodType: # Wrap the method in a converter
    #         return self.method_wrapper(output)
    #     else:
    #         return self.attribute_wrapper(output)

    def method_wrapper(self, function):
        """
        Wraps method with a label attacher such that whenever the method is called, the output is modified
        by adding the label.
        """

        def new_function(*args, **kwargs):

            output = function(*args, **kwargs)
            try:
                output = Message(output)
            except:
                return output

            return self.insert_labels(output)

        return new_function

    def attribute_wrapper(self, attribute):
        """
        Wraps attribute with new label if attribute returns a message.
        """
        try:
            output = Message(attribute)
        except:
            return attribute

        return self.insert_labels(output)

    def insert_labels(self, message):

        l = len(message)
        message[self.labels_column] = [self.label for _ in range(l)]

        return message

class LabelerPipe(Pipe):
    """
    This Pipe implements a to_tensor function that converts labels contained in messages to tensors based on an internal labels dict.
    """

    def __init__(self, labels, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.labels = labels
        self.labels_dict = bidict({label:i for label,i in zip(labels,count())})

    def to_tensor(self, batch, labels_column = 'labels'):

        batch['labels_name'] = batch[labels_column]
        labels = batch[labels_column]
        labels = [self.labels_dict[label] for label in labels]
        labels = torch.Tensor([one_hot(label,len(self.labels_dict)) for label in labels])
        batch['labels'] = labels
        try: # Allow an upstream Pipe to attempt to perform to_tensor if it can
            batch = self.recursive_call('to_tensor', batch)
            return batch
        except AttributeError:
            return batch

class RepeaterPipe(Pipe):
    """
    Given an input Pipe that is iterable, enables repeat iteration.
    """

    def __init__(self,*args,repetitions=10,**kwargs):
        super().__init__(*args,**kwargs)
        if not type(repetitions) is int:
            raise ValueError("Number of repetitions must be provided as an integer.")

        self.repetitions = repetitions

    def reset(self):
        self.iteration = 0
        self.recursive_call('reset',)()
        return self

    def __iter__(self):
        self.reset()
        return self

    def __next__(self):

        try:
            return self.recursive_call('__next__')()
        except StopIteration:
            self.iteration += 1
            if self.iteration >= self.repetitions:
                raise StopIteration
            else:
                self.recursive_call('reset')()
                return self.__next__()

class ShufflerPipe(Pipe):
    """
    Given input Pipes that implement __getitem__ and __len__, will shuffle the indices so that iterating through
    the Pipe or calling __getitem__ will return different values.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.check_inputs()
        self.current_index = 0
        self.shuffle_indices = np.array([i for i in range(len(self))])

    def check_inputs(self):
        """
        Check inputs to see if they implement __getitem__ and __len__
        """
        for name, pipe in self.input_pipes.items():
            if not (hasattr(pipe, '__getitem__')):
                raise TypeError('Pipe {0} does not have __getitem__ method.'.format(name))
            if not(hasattr(pipe, '__len__')):
                raise TypeError('Pipe {0} does not have __len__ method.'.format(name))

    def __getitem__(self, index):

        new_index = self.shuffle_indices[index]
        return self.recursive_call('__getitem__')(new_index.tolist())

    def __next__(self):

        if self.current_index >= len(self):
            raise StopIteration

        message = self[self.current_index]
        self.current_index += 1
        return message

    def shuffle(self, order = None): # TODO: Add support for ordering

        np.random.shuffle(self.shuffle_indices)

    def reset(self):
        """
        Triggers a shuffle on reset.
        """
        self.shuffle()
        self.current_index = 0
        try:
            self.recursive_call('reset')()
        except AttributeError:
            pass
        return self

    def __iter__(self):
        self.reset()
        return self

class IndexMapperPipe(Pipe):
    """
    Given input Pipes that implement __getitem__, returns a Pipe that maps indices in input_indices to output_indices via __getitem__
    """
    def __init__(self, input_indices, output_indices, *args,**kwargs):
        super().__init__(*args, **kwargs)
        self.check_inputs()
        if len(input_indices) != len(output_indices):
            raise ValueError("The number of input indices does not match the number of output indices.")
        self.pointers = UnlimitedCache()
        self.pointers[input_indices] = Message({'output':output_indices})

    def check_inputs(self):
        for name, pipe in self.input_pipes.items():
            if not hasattr(pipe, '__getitem__'):
                raise ValueError("Input Pipes must be indexable.")

    def __getitem__(self, index):

        index = index_to_list(index)
        return Fireworks.merge([pipe[self.pointers[index]['output'].values] for pipe in self.input_pipes.values()])

    def __len__(self):
        return len(self.pointers)

class BatchingPipe(Pipe):
    """
    Generates minibatches.
    """

    def __init__(self, *args, **kwargs):

        super().__init__(*args,**kwargs)
        self.current_index = 0
        self.batch_size = 5

    def __iter__(self):

        self.reset()
        return self

    def reset(self):

        self.current_index = 0

    def __next__(self):

        if self.current_index + self.batch_size > len(self):
            raise StopIteration

        try:
            batch = self[self.current_index:self.current_index+self.batch_size]
            self.current_index += self.batch_size
            return batch
        except IndexError:
            raise StopIteration
