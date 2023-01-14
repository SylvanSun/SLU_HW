# -*- coding:utf-8 -*-
import torch


def from_example_list(args, ex_list, device="cpu", train=True):
    ex_list = sorted(ex_list, key=lambda x: len(x.input_idx), reverse=True)
    batch = Batch(ex_list, device)
    pad_idx = args.pad_idx
    tag_pad_idx = args.tag_pad_idx

    batch.utt = [ex.utt for ex in ex_list]
    # print(batch.utt)
    input_lens = [len(ex.input_idx) for ex in ex_list]
    denoise_lens = [len(ex.denoise_idx) for ex in ex_list]
    for i in range(len(input_lens)):
        input_lens[i] = max(input_lens[i], denoise_lens[i])
    # print(input_lens)
    max_len = max(input_lens)
    input_ids = [ex.input_idx + [pad_idx] * (max_len - len(ex.input_idx)) for ex in ex_list]

    batch.input_ids = torch.tensor(input_ids, dtype=torch.long, device=device)
    # print(batch.input_ids.shape)
    batch.lengths = input_lens

    if train:
        denoise_ids = [ex.denoise_idx + [pad_idx] * (max_len - len(ex.denoise_idx)) for ex in ex_list]
        batch.denoise_ids = torch.tensor(denoise_ids, dtype=torch.long, device=device)

        batch.labels = [ex.slotvalue for ex in ex_list]
        tag_lens = [len(ex.tag_id) for ex in ex_list]
        max_tag_lens = max_len
        tag_ids = [ex.tag_id + [tag_pad_idx] * (max_tag_lens - len(ex.tag_id)) for ex in ex_list]
        tag_mask = [[1] * len(ex.tag_id) + [0] * (max_tag_lens - len(ex.tag_id)) for ex in ex_list]
        batch.tag_ids = torch.tensor(tag_ids, dtype=torch.long, device=device)
        batch.tag_mask = torch.tensor(tag_mask, dtype=torch.float, device=device)
    else:
        batch.labels = None
        batch.tag_ids = None
        batch.tag_mask = None
    return batch


class Batch:
    def __init__(self, examples, device):
        super(Batch, self).__init__()

        self.examples = examples
        self.device = device

    def __len__(self):
        return len(self.examples)

    def __getitem__(self, idx):
        return self.examples[idx]
