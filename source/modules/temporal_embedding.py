import numpy as np

import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

import math

class NormalLinear(nn.Linear):
    """
    Linear layer (weight matrix + bias vector) initialised with 0-mean Gaussian
    """

    def reset_parameters(self):
        stdv = 1. / math.sqrt(self.weight.size(1))
        self.weight.data.normal_(0, stdv)
        if self.bias is not None:
            self.bias.data.normal_(0, stdv)

class LinearProject(nn.Module):
    """
    Use to create Temporal Embedding from 1D input (e.g. time vector)
    (B x L_hist) -> (B x L_hist x D_e)
    """
    def __init__(self, d_in=1, d_model=768):
        super(LinearProject, self).__init__()

        #self.lin = NormalLinear(1, d_model)
        self.lin = nn.Linear(d_in, d_model)
        self.d_model = d_model
        self.d_in = d_in
        #self.lin.reset_parameters()

    @staticmethod
    def code():
        # linear projected temporal embedding
        return 'lte'

    def forward(self, t):
        # project single-value time stamps to temporal embedding
        # (B x L_hist) -> (B x L_hist x D_e)
        t = t.float()
        if len(t.shape) < 3:
            t_out = self.lin(t.unsqueeze(2))
        else:
            t_out = self.lin(t)
        return t_out
        # / math.sqrt(self.d_model)

class NeuralFunc(nn.Module):
    def __init__(self, d_in, d_model, hidden_units=[256, 768], act_func="relu"):
        super(NeuralFunc, self).__init__()

        assert d_model == hidden_units[-1], "Last layer with {} units must match embedding dimension {}".format(hidden_units[-1], d_model)

        self.lin_layers = nn.ModuleList()

        for i, hidden in enumerate(hidden_units):
            if 0 == i:
                self.lin_layers.append(nn.Linear(d_in, hidden))
            else:
                self.lin_layers.append(nn.Linear(hidden_units[i-1], hidden))

        func = act_func.lower()

        if "relu" == func:
            self.activation = nn.ReLU()
        elif "gelu" == func:
            raise NotImplementedError()
        elif "tanh" == func:
            self.activation = nn.Tanh()
        else:
            raise NotImplementedError()

    @staticmethod
    def code():
        # neural temporal embedding (func approx)
        return 'nte'

    def forward(self, x_in):
        if len(x_in.shape) < 3:
            x = x_in.unsqueeze(2).float()
        else:
            x = x_in.float()
        # input x: time stamp in vector format, e.g. [DD, HH, mm, ss]
        for i, lin in enumerate(self.lin_layers):
            if i < len(self.lin_layers)-1:
                x = self.activation(lin(x))
            else:
                x_out = lin(x)
        # (B x L x D_model)
        return x_out.squeeze()

TEMP_EMBS = {
    LinearProject.code(): LinearProject,
    NeuralFunc.code(): NeuralFunc
}