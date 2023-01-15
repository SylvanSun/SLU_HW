# coding=utf8
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.nn.utils.rnn as rnn_utils
from transformers import BertModel, BertTokenizer, logging
from utils.initialization import set_torch_device
from model.layers.crf import CRF

logging.set_verbosity_error()


class SLUTagging(nn.Module):
    def __init__(self, config):
        super(SLUTagging, self).__init__()
        self.device = set_torch_device(config.device)
        self.config = config
        self.cell = config.encoder_cell
        self.word_embed = nn.Embedding(config.vocab_size, config.embed_size, padding_idx=0)
        self.rnn = getattr(nn, self.cell)(
            config.embed_size,
            config.hidden_size // 2,
            num_layers=config.num_layer,
            bidirectional=True,
            batch_first=True,
        )
        self.dropout_layer = nn.Dropout(p=config.dropout)
        self.output_layer = TaggingFNNDecoder(config.hidden_size, config.num_tags, config.tag_pad_idx, config.crf)

    def forward(self, batch):
        tag_ids = batch.tag_ids  # (tensor) bs * S, where S is the longest sequence length
        tag_mask = batch.tag_mask  # (tensor) bs * S
        input_ids = batch.input_ids  # (tensor) bs * S
        lengths = batch.lengths  # (list) len = bs
        utt = batch.utt  # (list of str) len = bs
        B, S = tag_mask.shape
        embed = self.word_embed(input_ids) # (tensor) bs * 26 * 768

        transformer_out = embed

        packed_inputs = rnn_utils.pack_padded_sequence(transformer_out, lengths, batch_first=True, enforce_sorted=True)
        packed_rnn_out, h_t_c_t = self.rnn(packed_inputs)  # bsize x seqlen x dim
        rnn_out, unpacked_len = rnn_utils.pad_packed_sequence(packed_rnn_out, batch_first=True)  # B * S * hidden_size
        out = rnn_out
        hiddens = self.dropout_layer(out)  # bs * S * hidden_size
        tag_output = self.output_layer(hiddens, tag_mask, tag_ids)  # 2-tuple of length batchsize
        return tag_output

    def decode(self, label_vocab, batch):
        projection = self.config.projection.projection
        batch_size = len(batch)
        labels = batch.labels
        output = self.forward(batch)
        prob = output[0]
        predictions = []
        for i in range(batch_size):
            if self.config.crf:
                pred = prob[i]
            else:
                pred = torch.argmax(prob[i], dim=-1).cpu().tolist()
            pred_tuple = []
            idx_buff, tag_buff, pred_tags = [], [], []
            # print(pred)
            # print(len(batch.utt[i]))
            pred = pred[: len(batch.utt[i])]
            for idx, tid in enumerate(pred):
                tag = label_vocab.convert_idx_to_tag(tid)
                pred_tags.append(tag)
                if (tag == "O" or tag.startswith("B")) and len(tag_buff) > 0:
                    slot = "-".join(tag_buff[0].split("-")[1:])
                    value = "".join([batch.utt[i][j] for j in idx_buff])
                    idx_buff, tag_buff = [], []
                    projected = projection(slot.split("-")[-1], value)
                    if projected is not None:
                        pred_tuple.append(f"{slot}-{projected}")

                    if tag.startswith("B"):
                        idx_buff.append(idx)
                        tag_buff.append(tag)
                elif tag.startswith("I") or tag.startswith("B"):
                    idx_buff.append(idx)
                    tag_buff.append(tag)
            if len(tag_buff) > 0:
                slot = "-".join(tag_buff[0].split("-")[1:])
                value = "".join([batch.utt[i][j] for j in idx_buff])
                idx_buff, tag_buff = [], []
                projected = projection(slot.split("-")[-1], value)
                if projected is not None:
                    pred_tuple.append(f"{slot}-{projected}")
            predictions.append(pred_tuple)
        if len(output) == 1:
            return predictions
        else:
            loss = output[1]
            return predictions, labels, loss.cpu().item()


class TaggingFNNDecoder(nn.Module):
    def __init__(self, input_size, num_tags, pad_id, use_crf):
        super(TaggingFNNDecoder, self).__init__()
        self.use_crf = use_crf
        self.num_tags = num_tags
        self.output_layer = nn.Linear(input_size, num_tags)
        self.loss_fct = nn.CrossEntropyLoss(ignore_index=pad_id)
        if use_crf:
            self.crf = CRF(num_tags)

    def forward(self, hiddens, mask, labels=None):
        logits = self.output_layer(hiddens)
        logits += (1 - mask).unsqueeze(-1).repeat(1, 1, self.num_tags) * -1e32
        if self.use_crf:
            mask = mask.byte()
            prob = self.crf.viterbi_decode(logits, mask)  # list(len=32) of list(len=S) the values are predicted tags
        else:
            prob = torch.softmax(logits, dim=-1)
        if labels is not None:
            if self.use_crf:
                crf_out = self.crf(logits, labels, mask)
                loss = torch.mean(-crf_out)
            else:
                loss = self.loss_fct(logits.view(-1, logits.shape[-1]), labels.view(-1))
            return prob, loss
        return (prob,)
