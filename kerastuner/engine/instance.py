import json
import time
from collections import defaultdict
from os import path
import tensorflow as tf

from .execution import Execution
from kerastuner.states import InstanceState
from kerastuner.collections import ExecutionsCollection
from kerastuner.abstractions.display import section, subsection


class Instance(object):
    """Model instance class."""

    def __init__(self, idx, model, hparams, tuner_state, cloudservice):

        self.model = model
        self.tuner_state = tuner_state
        self.cloudservice = cloudservice
        self.executions = ExecutionsCollection()

        # init instance state
        self.state = InstanceState(idx, model, hparams)

    def summary(self, extended=False):
        section("Instance summary")
        self.state.summary(extended=extended)

    def fit_resume(self, fixme):
        """resume fiting an instance
        use execution id?
        """
        pass

    def fit_new(self, x, y, **kwargs):
        """Fit an execution of the model instance
        """

        # collect batch_size from the fit function
        self.state.batch_size = kwargs.get('batch_size', 32)

        # compute training_size and validation_size
        # in theory for batch training the function is __len__
        # should be implemented. However, for generator based training, __len__
        # returns the number of batches, NOT the training size.
        if isinstance(x, tf.keras.utils.Sequence):
            self.state.training_size = (len(x) + 2) * self.state.batch_size
        else:
            self.state.training_size = len(x)

        # Determine the validation size for the various validation strategies.
        if kwargs.get('validation_data'):
            self.state.validation_size = len(kwargs['validation_data'][1])
        elif kwargs.get('validation_split'):
            validation_split = kwargs.get('validation_split')
            val_size = self.state.training_size * validation_split
            self.state.validation_size = val_size
            self.state.training_size -= self.state.validation_size
        else:
            self.state.validation_size = 0

        # tell the user we are training a new instance
        if not len(self.executions):
            section("Training new instance")
            self.state.summary()
            if self.tuner_state.display_model:
                subsection("Model summary")
                self.model.summary()

        # FIXME we need to return properly results
        execution = Exception(self.model, self.state, self.tuner_state,
                              self.cloudservice)
        self.executions.add(len(self.executions), execution)
        results = execution.fit(x, y, **kwargs)

        # compute execution level metrics
        # FIXME can this be done in the in the execution fit instead of this?
        execution.record_results(results)

        # FIXME compute results and probably update the result file here
        return self

    def record_results(self):
        """Record training results
        Returns:
          dict: results data
        """

        results = self.__get_instance_info()
        local_dir = self.meta_data['server']['local_dir']

        # collecting executions results
        exec_metrics = defaultdict(lambda: defaultdict(list))
        executions = []  # execution data
        for execution in self.executions:

            # metrics collection
            for metric, data in execution.metrics.items():
                exec_metrics[metric]['min'].append(
                    execution.metrics[metric]['min'])
                exec_metrics[metric]['max'].append(
                    execution.metrics[metric]['max'])

            try:
                json.dumps(execution.model.loss)
                reported_loss_fns = execution.model.loss
            except:
                reported_loss_fns = "CUSTOM"

            # execution data
            execution_info = {
                "num_epochs": execution.num_epochs,
                "history": execution.history,
                "loss_fn": reported_loss_fns,
                "loss_weights": execution.model.loss_weights,
                "meta_data": execution.meta_data,
            }
            executions.append(execution_info)

            # cleanup memory
            del execution.model
            self._clear_gpu_memory()

        results['executions'] = executions
        results['meta_data'] = self.meta_data

        # aggregating statistics
        metrics = defaultdict(dict)
        for metric in exec_metrics.keys():
            for direction, data in exec_metrics[metric].items():
                metrics[metric][direction] = {
                    "min": float(np.min(data)),
                    "max": float(np.max(data)),
                    "mean": float(np.mean(data)),
                    "median": float(np.median(data))
                }
        results['metrics'] = metrics

        # Usual metrics reported as top fields for their median values
        for tm in self.key_metrics:
            if tm[0] in metrics:
                results['key_metrics'][tm[0]] = metrics[tm[0]][tm[1]]['median']

        fname = '%s-%s-%s-results.json' % (self.meta_data['project'],
                                           self.meta_data['architecture'],
                                           self.meta_data['instance'])
        local_path = path.join(local_dir, fname)
        with file_io.FileIO(local_path, 'w') as outfile:
            outfile.write(json.dumps(results))

        # cloud recording if needed
        if self.backend:
            self.backend.send_results(results)

        self.results = results
        return results
