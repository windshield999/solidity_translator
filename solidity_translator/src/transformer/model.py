"""
Please refer to the following website for the details. This file in based almost exactly on the tutorial.
http://nlp.seas.harvard.edu/2018/04/03/attention.html
"""


import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import math, copy, time
from torch.autograd import Variable


from src.language_rules.expressions import Expression
from src.language_rules.templates import Template


# A list of todos.
# TODO define the vocab as well as the embedding for the restricted natural language
# TODO define the vocab as well as the embedding for the solidity code


class EncoderDecoder(nn.Module):
    """
    A standard Encoder-Decoder architecture. Base for this and many
    other models.
    """
    
    def __init__(self, encoder, decoder, src_embed, tgt_embed, generator):
        super(EncoderDecoder, self).__init__()
        self.encoder = encoder
        self.decoder = decoder
        self.src_embed = src_embed
        self.tgt_embed = tgt_embed
        self.generator = generator
    
    def forward(self, src, tgt, src_mask, tgt_mask):
        """
        Take in and process masked src and target sequences.
        """
        return self.decode(self.encode(src, src_mask), src_mask,
                           tgt, tgt_mask)
    
    def encode(self, src, src_mask):
        return self.encoder(self.src_embed(src), src_mask)
    
    def decode(self, memory, src_mask, tgt, tgt_mask):
        return self.decoder(self.tgt_embed(tgt), memory, src_mask, tgt_mask)
    
    
class Generator(nn.Module):
    """
    Define standard linear + softmax generation step.
    """
    def __init__(self, d_model, vocab_size):
        super(Generator, self).__init__()
        self.proj = nn.Linear(d_model, vocab_size)

    def forward(self, x):
        return F.log_softmax(self.proj(x), dim=-1)
    

def clones(module, N):
    """
    Produce N identical layers.
    """
    return nn.ModuleList([copy.deepcopy(module) for _ in range(N)])


class Encoder(nn.Module):
    """
    Core encoder is a stack of N layers
    """
    
    def __init__(self, layer, N):
        super(Encoder, self).__init__()
        self.layers = clones(layer, N)
        self.norm = LayerNorm(layer.size)
    
    def forward(self, x, mask):
        """
        Pass the input (and mask) through each layer in turn.
        """
        for layer in self.layers:
            x = layer(x, mask)
        return self.norm(x)


class EncoderLayer(nn.Module):
    """
    Encoder is made up of self-attn and feed forward (defined below)
    """

    def __init__(self, size, self_attn, feed_forward, dropout):
        super(EncoderLayer, self).__init__()
        self.self_attn = self_attn
        self.feed_forward = feed_forward
        self.sublayer = clones(SublayerConnection(size, dropout), 2)
        self.size = size

    def forward(self, x, mask):
        """
        Follow Figure 1 (left) for connections.
        """
        x = self.sublayer[0](x, lambda _x: self.self_attn(_x, _x, _x, mask))
        return self.sublayer[1](x, self.feed_forward)


class Decoder(nn.Module):
    """
    Generic N layer decoder with masking.
    """

    def __init__(self, layer, N):
        super(Decoder, self).__init__()
        self.layers = clones(layer, N)
        self.norm = LayerNorm(layer.size)

    def forward(self, x, memory, src_mask, tgt_mask):
        for layer in self.layers:
            x = layer(x, memory, src_mask, tgt_mask)
        return self.norm(x)


class DecoderLayer(nn.Module):
    """
    Decoder is made of self-attn, src-attn, and feed forward (defined below)
    """

    def __init__(self, size, self_attn, src_attn, feed_forward, dropout):
        super(DecoderLayer, self).__init__()
        self.size = size
        self.self_attn = self_attn
        self.src_attn = src_attn
        self.feed_forward = feed_forward
        self.sublayer = clones(SublayerConnection(size, dropout), 3)

    def forward(self, x, memory, src_mask, tgt_mask):
        """
        Follow Figure 1 (right) for connections.
        """
        m = memory
        x = self.sublayer[0](x, lambda _x: self.self_attn(_x, _x, _x, tgt_mask))
        x = self.sublayer[1](x, lambda _x: self.src_attn(_x, m, m, src_mask))
        return self.sublayer[2](x, self.feed_forward)


class LayerNorm(nn.Module):
    """
    Construct a layernorm module (See citation for details).
    """
    # features is simply an int indicating the size of input.
    def __init__(self, features, eps=1e-6):
        super(LayerNorm, self).__init__()
        self.a_2 = nn.Parameter(torch.ones(features))
        self.b_2 = nn.Parameter(torch.zeros(features))
        self.eps = eps

    def forward(self, x):
        mean = x.mean(-1, keepdim=True)
        std = x.std(-1, keepdim=True)
        return self.a_2 * (x - mean) / (std + self.eps) + self.b_2
    

class SublayerConnection(nn.Module):
    """
    A residual connection followed by a layer norm.
    Note for code simplicity the norm is first as opposed to last.
    """
    def __init__(self, size, dropout):
        super(SublayerConnection, self).__init__()
        self.norm = LayerNorm(size)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x, sublayer):
        """
        Apply residual connection to any sublayer with the same size.
        """
        return x + self.dropout(sublayer(self.norm(x)))
    
    
def subsequent_mask(size):
    """
    Mask out subsequent positions.
    """
    attn_shape = (1, size, size)
    _subsequent_mask = np.triu(np.ones(attn_shape), k=1).astype('uint8')
    return torch.from_numpy(_subsequent_mask) == 0


def attention(query, key, value, mask=None, dropout=None):
    """
    Compute 'Scaled Dot Product Attention'
    """
    d_k = query.size(-1)
    scores = torch.matmul(query, key.transpose(-2, -1)) \
             / math.sqrt(d_k)
    if mask is not None:
        scores = scores.masked_fill(mask == 0, -1e9)
    p_attn = F.softmax(scores, dim = -1)
    if dropout is not None:
        p_attn = dropout(p_attn)
    return torch.matmul(p_attn, value), p_attn


class MultiHeadedAttention(nn.Module):
    def __init__(self, h, d_model, dropout=0.1):
        """
        Take in model size and number of heads.
        """
        super(MultiHeadedAttention, self).__init__()
        assert d_model % h == 0
        # We assume d_v always equals d_k
        self.d_k = d_model // h
        self.h = h
        self.linears = clones(nn.Linear(d_model, d_model), 4)
        self.attn = None
        self.dropout = nn.Dropout(p=dropout)
    
    def forward(self, query, key, value, mask=None):
        """
        Implements Figure 2
        """
        if mask is not None:
            # Same mask applied to all h heads.
            mask = mask.unsqueeze(1)
        nbatches = query.size(0)
        
        # 1) Do all the linear projections in batch from d_model => h x d_k
        query, key, value = \
            [l(x).view(nbatches, -1, self.h, self.d_k).transpose(1, 2)
             for l, x in zip(self.linears, (query, key, value))]
        
        # 2) Apply attention on all the projected vectors in batch.
        x, self.attn = attention(query, key, value, mask=mask,
                                 dropout=self.dropout)
        
        # 3) "Concat" using a view and apply a final linear.
        x = x.transpose(1, 2).contiguous() \
            .view(nbatches, -1, self.h * self.d_k)
        return self.linears[-1](x)
    

class PositionwiseFeedForward(nn.Module):
    """
    Implements FFN equation.
    """
    def __init__(self, d_model, d_ff, dropout=0.1):
        super(PositionwiseFeedForward, self).__init__()
        self.w_1 = nn.Linear(d_model, d_ff)
        self.w_2 = nn.Linear(d_ff, d_model)
        self.dropout = nn.Dropout(dropout)

    def forward(self, x):
        return self.w_2(self.dropout(F.relu(self.w_1(x))))


class Embeddings(nn.Module):
    def __init__(self, d_model, vocab_size):
        super(Embeddings, self).__init__()
        self.lut = nn.Embedding(vocab_size, d_model)
        self.d_model = d_model

    def forward(self, x):
        return self.lut(x) * math.sqrt(self.d_model)


class PositionalEncoding(nn.Module):
    """
    Implement the PE function.
    """
    
    def __init__(self, d_model, dropout, max_len=5000):
        super(PositionalEncoding, self).__init__()
        self.dropout = nn.Dropout(p=dropout)
        
        # Compute the positional encodings once in log space.
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2) *
                             -(math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        pe = pe.unsqueeze(0)
        self.register_buffer('pe', pe)
    
    def forward(self, x):
        # The size of the encoding table is 5000 by default, which is fixed.
        # Depending on how long x is, the encoding's length may vary.
        x = x + Variable(self.pe[:, :x.size(1)],
                         requires_grad=False)
        return self.dropout(x)


def make_transformer_model(src_vocab_size, tgt_vocab_size, N=6,
               d_model=512, d_ff=2048, h=8, dropout=0.1):
    """
    Helper: Construct a model from hyperparameters.
    """
    c = copy.deepcopy
    attn = MultiHeadedAttention(h, d_model)
    ff = PositionwiseFeedForward(d_model, d_ff, dropout)
    position = PositionalEncoding(d_model, dropout)
    model = EncoderDecoder(
        Encoder(EncoderLayer(d_model, c(attn), c(ff), dropout),
                N),
        Decoder(DecoderLayer(d_model, c(attn), c(attn), c(ff), dropout),
                N),
        nn.Sequential(Embeddings(d_model, src_vocab_size), c(position)),
        nn.Sequential(Embeddings(d_model, tgt_vocab_size), c(position)),
        Generator(d_model, tgt_vocab_size))
    
    # This was important from their code.
    # Initialize parameters with Glorot / fan_avg.
    for p in model.parameters():
        if p.dim() > 1:
            nn.init.xavier_uniform(p)
    return model


class Batch:
    """
    Object for holding a batch of data with mask during training.
    """
    
    def __init__(self, src, trg=None, pad=0):
        self.src = src
        self.src_mask = (src != pad).unsqueeze(-2)
        if trg is not None:
            self.trg = trg[:, :-1]
            self.trg_y = trg[:, 1:]
            self.trg_mask = \
                self.make_std_mask(self.trg, pad)
            self.ntokens = (self.trg_y != pad).data.sum()
    
    @staticmethod
    def make_std_mask(tgt, pad):
        """
        Create a mask to hide padding and future words.
        """
        tgt_mask = (tgt != pad).unsqueeze(-2)
        tgt_mask = tgt_mask & Variable(
            subsequent_mask(tgt.size(-1)).type_as(tgt_mask.data))
        return tgt_mask
    

def run_epoch(data_iter, model, loss_compute):
    """
    Standard Training and Logging Function
    """
    start = time.time()
    total_tokens = 0
    total_loss = 0
    tokens = 0
    for i, batch in enumerate(data_iter):
        out = model.forward(batch.src, batch.trg,
                            batch.src_mask, batch.trg_mask)
        loss = loss_compute(out, batch.trg_y, batch.ntokens)
        total_loss += loss
        total_tokens += batch.ntokens
        tokens += batch.ntokens
        if i % 50 == 1:
            elapsed = time.time() - start
            print("Epoch Step: %d Loss: %f Tokens per Sec: %f" %
                    (i, loss / batch.ntokens, tokens / elapsed))
            start = time.time()
            tokens = 0
    return total_loss / total_tokens


# global max_src_in_batch, max_tgt_in_batch
def batch_size_fn(new, count, sofar):
    """
    Keep augmenting batch and calculate total number of tokens + padding.
    """
    global max_src_in_batch, max_tgt_in_batch
    if count == 1:
        max_src_in_batch = 0
        max_tgt_in_batch = 0
    max_src_in_batch = max(max_src_in_batch,  len(new.src))
    max_tgt_in_batch = max(max_tgt_in_batch,  len(new.trg) + 2)
    src_elements = count * max_src_in_batch
    tgt_elements = count * max_tgt_in_batch
    return max(src_elements, tgt_elements)


class NoamOpt:
    """
    Optim wrapper that implements rate.
    """
    
    def __init__(self, model_size, factor, warmup, optimizer):
        self.optimizer = optimizer
        self._step = 0
        self.warmup = warmup
        self.factor = factor
        self.model_size = model_size
        self._rate = 0
    
    def step(self):
        """
        Update parameters and rate
        """
        self._step += 1
        rate = self.rate()
        for p in self.optimizer.param_groups:
            p['lr'] = rate
        self._rate = rate
        self.optimizer.step()
    
    def rate(self, step=None):
        """
        Implement `lrate` above
        """
        if step is None:
            step = self._step
        return self.factor * \
               (self.model_size ** (-0.5) *
                min(step ** (-0.5), step * self.warmup ** (-1.5)))


def get_std_opt(model):
    return NoamOpt(model.src_embed[0].d_model, 2, 4000,
                   torch.optim.Adam(model.parameters(), lr=0, betas=(0.9, 0.98), eps=1e-9))

# TODO might need to change / remove this.
class LabelSmoothing(nn.Module):
    """
    Implement label smoothing.
    """
    
    def __init__(self, size, padding_idx, smoothing=0.0):
        super(LabelSmoothing, self).__init__()
        self.criterion = nn.KLDivLoss(size_average=False)
        self.padding_idx = padding_idx
        self.confidence = 1.0 - smoothing
        self.smoothing = smoothing
        self.size = size
        self.true_dist = None
    
    def forward(self, x, target):
        assert x.size(1) == self.size
        true_dist = x.data.clone()
        true_dist.fill_(self.smoothing / (self.size - 2))
        true_dist.scatter_(1, target.data.unsqueeze(1), self.confidence)
        true_dist[:, self.padding_idx] = 0
        mask = torch.nonzero(target.data == self.padding_idx)
        if mask.dim() > 0:
            true_dist.index_fill_(0, mask.squeeze(), 0.0)
        self.true_dist = true_dist
        return self.criterion(x, Variable(true_dist, requires_grad=False))
    

class Vocab:
    def __init__(self, vocab: [str]):
        self.vocab = vocab
        self.word2index = {}
        self.index2word = {}

        cnt = 0
        for word in self.vocab:
           self.word2index[word] = cnt
           self.index2word[cnt] = word
           cnt += 1

    def index_of_word(self, word: str):
        return self.word2index[word]

    def word_at_index(self, index: int):
        return self.index2word[index]

# Transformer translation only supports integer for now.
def get_description_vocab(allowed_variable_names: [str], syntax_tokens, number_range: (int, int)) -> [str]:
    vocab = []
    vocab.extend(['unk_tkn', 'pad_tkn', '[', ']', 'contract', 'function', 'for', ':', ',', '.'])
    vocab.extend(allowed_variable_names)
    vocab.extend(Expression.get_description_vocab())
    vocab.extend(Template.get_description_vocab())
    vocab.extend(syntax_tokens)

    assert number_range[0] < number_range[1]
    vocab.extend(list(map(lambda n: str(n), np.arange(number_range[0], number_range[1]))))
    return Vocab(list(set(vocab)))



def get_solidity_vocab(allowed_variable_names: [str], syntax_tokens, number_range: (int, int)) -> [str]:
    vocab = []
    vocab.extend(['unk_tkn', 'pad_tkn', '[', ']', '(', ')', '{', '}', ';', '.', ','])
    vocab.extend(allowed_variable_names)
    vocab.extend(Expression.get_solidity_vocab())
    vocab.extend(Template.get_solidity_vocab())
    vocab.extend(syntax_tokens)

    assert number_range[0] < number_range[1]
    vocab.extend(list(map(lambda n: str(n), np.arange(number_range[0], number_range[1]))))
    return Vocab(list(set(vocab)))


# A list of example descriptions to refer to...
# The following defines the contract Q
# It emits the following: [9517]
# This is the end of the description of the contract Q
# *******************************************
# The following defines the contract W
# It emits the following: [true]
# This is the end of the description of the contract W
# *******************************************
# The following defines the contract u
# This contract has an enum called h that has Z, C, N, r
# This contract has a bytes32 variable called y with an assigned value [the calling of [W] with argument(s) [[the product of [k] and [-1990]]]]
# This contract checks [the equal relationship of [the calling of [t] with argument(s) [[the equal relationship of [an enum which is [D] of [J]] and [154]], [8167], [the calling of [A] with argument(s) [[false]]], [an enum which is [F] of [O]], [an enum which is [t] of [z]]]] and [true]]
# It emits the following: [8718]
# This contract has an enum called U that has S, X
# This is the end of the description of the contract u
def tokenize_description(text: str) -> [str]:
    # add space to ':', '[', ']', ',', '.'
    text = text\
        .replace(':', ' :')\
        .replace('[', '[ ')\
        .replace(']', ' ]')\
        .replace(',', ' ,')\
        .replace('.', ' . ')

    return list(map(lambda s: s.strip(' '), text.lower().split(' ')))


# A list of example codes are given below to refer to...
# contract u {
# 	enum h {Z, C, N, r}
# 	bytes32 y = W((k * -1990));
# 	require((t((J.D == 154), 8167, A(false), O.F, z.t) == true));
# 	emit 8718
# 	enum U {S, X}
# }
# *******************************************
# contract J {
# 	require(((-3568 * v(-6701, 3681, A.s)) == 1995));
# 	address u = D.g;
# 	emit true
# 	enum j {U}
# 	require((C.t == 281));
# }
# *******************************************
# contract Q {
# 	enum i {u, B, b}
# 	emit (-9078 * v)
# 	function a(int s, float A, uint W, address Y, boolean e) public  {
# 		require((g.I == E(true, (P == I.p))));
# 	}
# }
def tokenize_solidity_code(text: str) -> [str]:
    text = text\
        .replace('{', ' { ')\
        .replace('}', ' } ')\
        .replace('(', ' ( ')\
        .replace(')', ' ) ')\
        .replace('.', ' . ')\
        .replace(';', ' ; ')\
        .replace(',', ' , ')
    tokens = list(map(lambda s: s.strip(' '), text.lower().split(' ')))
    while '' in tokens:
        tokens.remove('')

    return tokens


def convert_text_to_indices(text: str):
    # note the case where a token may not appear in the vocab - use unk_tkn!
    pass



VAR_OPTIONS_SET = [
    'uint',
    'int',
    'double',
    'float',
    'address',
    'bytes32',
    'boolean',
]

FUNC_OPTIONS_SET = [
    'public',
    'private',
]


def test_tokenizers():
    descriptions = ['This contract has a bytes32 variable called y with an assigned value [the calling of [W] with argument(s) [[the product of [k] and [-1990]]]]',
         'This contract checks [the equal relationship of [the calling of [t] with argument(s) [[the equal relationship of [an enum which is [D] of [J]] and [154]], [8167], [the calling of [A] with argument(s) [[false]]], [an enum which is [F] of [O]], [an enum which is [t] of [z]]]] and [true]]']
    tokens = tokenize_description(descriptions[0]) + tokenize_description(descriptions[1])

    allowed_variable_names = 'a b c d e f g h i j k l m n o p q r s t u v w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z'.split()
    number_range = (-10000, 10000)
    description_vocab = get_description_vocab(allowed_variable_names, VAR_OPTIONS_SET + FUNC_OPTIONS_SET, number_range)
    solidity_vocab = get_solidity_vocab(allowed_variable_names, VAR_OPTIONS_SET + FUNC_OPTIONS_SET, number_range)

    for token in tokens:
        if token not in description_vocab.vocab:
            print('This token is not in the description_vocab!', token)

    codes = [
        'require((t((J.D == 154), 8167, A(false), O.F, z.t) == true));',
        'bytes32 y = W((k * -1990));',
        'function a(int s, float A, uint W, address Y, boolean e) public {',
    ]
    tokens = tokenize_solidity_code(codes[0]) + tokenize_solidity_code(codes[1]) + tokenize_solidity_code(codes[2])

    for token in tokens:
        if token not in solidity_vocab.vocab:
            print('This token is not in the solidity_vocab!', token)


def main():
    allowed_variable_names = 'a b c d e f g h i j k l m n o p q r s t u v w x y z A B C D E F G H I J K L M N O P Q R S T U V W X Y Z'.split()
    number_range = (-10000, 10000)

    description_vocab = get_description_vocab(allowed_variable_names, VAR_OPTIONS_SET + FUNC_OPTIONS_SET, number_range)
    solidity_vocab = get_solidity_vocab(allowed_variable_names, VAR_OPTIONS_SET + FUNC_OPTIONS_SET, number_range)




if __name__ == '__main__':
    # main()
    test_tokenizers()