# -*- coding: utf-8 -*-
"""
Created on Sun Feb 28 06:48:49 2021
"""

import torch
import torch.nn as nn
import torch.nn.functional as F

import torch_scatter
from torch_geometric.nn.conv import MessagePassing

class GeneralGraphLayer(MessagePassing):
    """ A general graph layer.  
    
    Performs:
    1) Propagate messages
    2) Aggregate messages
    3) Update node representation
    
    Implemented based on Gu (2017), equation 1 https://arxiv.org/abs/2009.06211
    """
    def __init__(self, 
                 in_channels: int, 
                 out_channels: int,
                 node_channels: int, 
                 activation_fn = F.relu,
                 node_dim = 0,
                 node_feature_bias = True,
                 node_embedding_bias = True,
                 **kwargs):  
        super(GeneralGraphLayer, self).__init__(**kwargs)
        # Node feature weights. Named \phi in paper equation (1)
        self.phi = nn.Linear(node_channels, out_channels)
        # Node embedding weights. Named W in paper equation (1)
        self.W = nn.Linear(in_channels, out_channels)
        # Nonlinearity to apply
        self.activation_fn = activation_fn
        # The dimension corresponding to different nodes. 
        # E.g. if inputs are (num_nodes, node_dim) then node_dim = 0
        # Used in self.aggregate
        self.node_dim = node_dim
        
    def reset_parameters(self):
        """
        Use Kaiming initialization.
        Greatly improves convergence for deep nets using ReLU.
        A recurrent neural net is infinitely deep. 
        Source: https://pouannes.github.io/blog/initialization/
        """
        nn.init.kaiming_uniform_(self.phi.weights)
        nn.init.kaiming_uniform_(self.W.weights)
        if self.node_feature_bias: nn.init.uniform_(self.phi.bias)
        if self.node_embedding_bias: nn.init.uniform_(self.W.bias)
    
    def forward(self, x, u, edge_index):
        """
        @param x: 
            Hidden node representation at step T.
            Shape: (batch_size, hidden_dim)
        @param u: 
            Base node features. 
            Shape: (batch_size, node_dim)
        @param edge_index: 
            A tensor containing (source, target) node indexes
            Shape: (2, num_edges)
    
        @return: Node representation at step T+1. 
        """
        x = self.W(x)
        x = self.propagate(edge_index, x=(x,x))
        x = x + self.U(u)
        x = self.activation_fn(x)
        return x
    
    def message(self, x_j):
        """
        Get the message that neighbouring nodes pass to this node. 
        
        @param x_j: 
            Hidden representation of neighbouring nodes.
        """
        return x_j

    def aggregate(self, inputs, index, dim_size = None):
        return torch_scatter.scatter(inputs, index, dim=self.node_dim, 
                             dim_size=dim_size, reduce="sum")

class RecurrentGraphNeuralNet(torch.nn.Module):
    """ 
    Recurrent graph neural net model. 
    
    Idea: 
        A feedforward GNN has k layers limiting aggregation to k hops away. 
        Recurrent GNN has infinite layers that share the same parameters.
        This enables aggregation from any distance away. 
        Hidden state is computed based on node features and previous hidden state. 
        
    Details:
        When training the model, initialize a random embedding for each node
        at the start. As the model is trained, the embedding will converge to
        a good embedding. 
    
    Implemented based on Gu (2017), equation 1 https://arxiv.org/abs/2009.06211
    """
    def __init__(self, 
             node_channels: int,
             hidden_channels: int,
             prediction_channels: int,
             **kwargs):  
        self.graph_layer = GeneralGraphLayer(
            in_channels = hidden_channels, 
            out_channels = hidden_channels, 
            node_channels = node_channels, **kwargs)
        self.prediction_head = nn.Linear(hidden_channels, prediction_channels)
        
    def reset_parameters(self):
        self.graph_layer.reset_parameters()
        self.prediction_head.reset_parameters()
    
    def forward(self, x, u, edge_index):
        """        
        @param x: 
            Hidden node representation at step T.
            Shape: (batch_size, hidden_channels)
        @param u: 
            Base node features. 
            Shape: (batch_size, node_channels)
        @param edge_index: 
            A tensor containing (source, target) node indexes
            Shape: (2, num_edges)
            
        @return x: Hidden node representation at step T+1. 
        @return y: Model outputs at step T+1. 
        """
        x = self.graph_layer(x, u, edge_index)
        y = self.prediction_head(x)
        return x, y
    
class DeepSnapWrapper(torch.nn.Module):
    """
    Wrap a model to accept DeepSnap batches instead of raw tensors. 
    """
    def __init__(self, model): 
        """
        @param model:
            torch.nn.Module
            expected signature: model(x, u, edge_index)
        """
        self.model = model 
        
    def reset_parameters(self):
        self.model.reset_parameters()
    
    def forward(self, batch):
        """        
        @param batch:
            A DeepSnap.Batch object
        """
        x = batch.node_embedding
        u = batch.node_feature
        edge_index = batch.edge_index
        return self.model(x, u, edge_index)