import copy

import torch
from torch import nn
from torch.nn import functional as F
from torchcrf import CRF


def keras_lstm(inputs, hidden):
    layer = nn.LSTM(inputs, hidden, batch_first=True)
    nn.init.xavier_uniform_(layer.weight_ih_l0)
    nn.init.orthogonal_(layer.weight_hh_l0)
    with torch.no_grad():
        layer.bias_ih_l0.zero_(); layer.bias_ih_l0[hidden:2 * hidden].fill_(1)
        layer.bias_hh_l0.zero_()
    layer.bias_hh_l0.requires_grad_(False)
    return layer


class LinearChain(nn.Module):
    def __init__(self, states):
        super().__init__(); self.crf = CRF(states, batch_first=True)
        with torch.no_grad():
            self.crf.start_transitions.zero_(); self.crf.end_transitions.zero_()
        self.crf.start_transitions.requires_grad_(False); self.crf.end_transitions.requires_grad_(False)

    def log_likelihood(self, emissions, labels):
        return self.crf(emissions, labels, mask=torch.ones_like(labels, dtype=torch.bool), reduction="none")

    def decode(self, emissions, ordered=False):
        chain = self.crf
        if ordered:
            chain = copy.deepcopy(chain)
            # Lottery regions are sets; strict increasing paths rule out repeats without rejection loops.
            with torch.no_grad():
                invalid = torch.tril(torch.ones_like(chain.transitions, dtype=torch.bool))
                chain.transitions.masked_fill_(invalid, -10000.)
        return chain.decode(emissions, mask=torch.ones(emissions.shape[:2], dtype=torch.bool, device=emissions.device))


class RecurrentDropLSTM(nn.Module):
    """Keras-style locked recurrent masks, independently sampled for the four gates."""
    def __init__(self, inputs, hidden, dropout=.2):
        super().__init__(); self.hidden = hidden; self.dropout = dropout
        self.kernel = nn.Parameter(torch.empty(4 * hidden, inputs))
        self.recurrent = nn.Parameter(torch.empty(4 * hidden, hidden))
        self.bias = nn.Parameter(torch.zeros(4 * hidden))
        nn.init.xavier_uniform_(self.kernel); nn.init.orthogonal_(self.recurrent)
        with torch.no_grad(): self.bias[hidden:2 * hidden].fill_(1)

    def forward(self, values):
        h = values.new_zeros(values.shape[0], self.hidden); cell = torch.zeros_like(h)
        masks = values.new_ones(4, values.shape[0], self.hidden)
        if self.training and self.dropout:
            masks = torch.bernoulli(masks * (1 - self.dropout)) / (1 - self.dropout)
        recurrent_weights = self.recurrent.chunk(4, dim=0)
        for step in values.unbind(dim=1):
            projected = F.linear(step, self.kernel, self.bias).chunk(4, dim=-1)
            i, f, g, o = [projected[k] + F.linear(h * masks[k], recurrent_weights[k]) for k in range(4)]
            cell = f.sigmoid() * cell + i.sigmoid() * g.tanh()
            h = o.sigmoid() * cell.tanh()
        return h


class FrontModel(nn.Module):
    def __init__(self, states, count, embedding=32, hidden=32):
        super().__init__(); self.count = count
        self.embedding = nn.Embedding(states, embedding)
        self.temporal = nn.ModuleList([keras_lstm(embedding, hidden) for _ in range(count)])
        self.position = keras_lstm(hidden, hidden)
        self.output = nn.Linear(hidden, states); self.chain = LinearChain(states)

    def forward(self, values):
        embedded = self.embedding(values)
        positions = [self.temporal[i](embedded[:, :, i])[0][:, -1] for i in range(self.count)]
        features = self.position(torch.stack(positions, dim=1))[0]
        return self.output(features)


class BackModel(nn.Module):
    def __init__(self, states, embedding=32, hidden=32):
        super().__init__(); self.embedding = nn.Embedding(states, embedding)
        self.first = keras_lstm(embedding, hidden); self.second = keras_lstm(hidden, hidden)
        self.final = RecurrentDropLSTM(hidden, hidden, .2); self.output = nn.Linear(hidden, states)

    def forward(self, values):
        features = self.first(self.embedding(values))[0]
        features = self.second(features)[0]
        return self.output(self.final(features))
