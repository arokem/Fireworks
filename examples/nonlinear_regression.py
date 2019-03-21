import Fireworks
from Fireworks import Message
from Fireworks.extensions import IgniteJunction, Experiment
from ignite.metrics import Metric

import torch
from copy import deepcopy
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.animation import FuncAnimation

from examples.nonlinear_regression_utils import NonlinearModel, get_data
# from examples.database_example import get_data

description = "In this experiment, we are training a polynomial model using least squares regression to fit data generated by a random polynomial."
experiment = Experiment("nonlinear_regression", description=description)

train_set, test_set, params = get_data(n=1000)

model = NonlinearModel()
# model = NonlinearModel(components={'d': [0], 'e':[0]})
# model.freeze(['d','e'])

# Construct training closure and train using ignite
base_loss = torch.nn.MSELoss()
loss = lambda batch: base_loss(batch['y_pred'], batch['y'])
trainer = IgniteJunction(components={'model': model, 'dataset': train_set}, loss=loss, optimizer='Adam', lr=.1, visdom=False)

class ModelSaverMetric(Metric):

    def __init__(self, output_transform=lambda x:x, log_interval=100):
        self.model_state = Message()
        Metric.__init__(self, output_transform=output_transform)
        self.log_interval = log_interval

    def iteration_completed(self, engine):
            iter = (engine.state.iteration-1)
            if iter % self.log_interval == 0:
                current_state = Message.from_objects(deepcopy(engine.state.output['state']))
                current_state['iteration'] = [iter]
                self.model_state = self.model_state.append(current_state)

    def compute(self):
        # Return most recent model state
        l = len(self.model_state)
        return self.model_state[l-1]

if __name__== "__main__":

    model_state_metric = ModelSaverMetric()
    model_state_metric.attach(trainer, 'state')

    x = Message({'x':np.arange(-10,10,.2)}).to_tensors()

    # Run initial evaluation
    y_initial = model(x)['y_pred'].detach().numpy()
    initial_loss = loss(model(test_set[0:250]))
    print("Initial loss on test set: {0}".format(initial_loss))

    # Save initial state of model
    file_path = experiment.open('initial_model', string_only=True)
    initial_state = model.get_state()
    Message.from_objects(initial_state).to('json', path=file_path)

    trainer.train(max_epochs=200)

    final_loss = loss(model(test_set[0:250]))
    print("Final loss on test set:: {0}".format(final_loss))

    # Visualize functions
    true_model = NonlinearModel(components={'a':[params['a']], 'b': [params['b']], 'c': [params['c']], 'd': [0], 'e': [0]})

    y_true = true_model(x)['y_pred'].detach().numpy()
    y_final = model(x)['y_pred'].detach().numpy()

    # Save model states during training
    file_path = experiment.open('model_states', string_only=True)
    model_states = model_state_metric.model_state
    Message.from_objects(initial_state).to('json', path=file_path)

    fig, ax = plt.subplots()

    def animate(frame):

        current_state = {'internal': frame['internal'][0], 'external': {}}
        model.set_state(current_state)

        y_predicted = model(x)['y_pred'].detach().numpy()
        xdata = list(x['x'].detach().numpy())
        ydata = list(y_predicted)
        ax.clear()
        ax.plot(xdata, list(y_true), 'r')
        ax.plot(xdata, ydata, 'g')
        title = "Iteration: {0}".format(frame['iteration'][0])

        ax.set_title(title)

    ani = FuncAnimation(fig, animate, model_state_metric.model_state, interval=1000)
    ani.save(experiment.open("models.mp4", string_only=True)) # This will only work if you have ffmpeg installed.
    plt.show()
