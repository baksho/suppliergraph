"""TransE and RotatE in plain PyTorch (compact, no PyKEEN dependency; see docs/evaluation.md).

References (from memory; check before citing): Bordes et al. 2013 (TransE); Sun et al. 2019 (RotatE,
with self-adversarial negative sampling). Both models return a *distance* (lower = more plausible).
"""
from __future__ import annotations

import math

import torch
from torch import nn


class TransE(nn.Module):
    def __init__(self, n_ent: int, n_rel: int, dim: int = 64, p: int = 1):
        super().__init__()
        self.dim, self.p = dim, p
        self.ent = nn.Embedding(n_ent, dim)
        self.rel = nn.Embedding(n_rel, dim)
        bound = 6.0 / math.sqrt(dim)
        nn.init.uniform_(self.ent.weight, -bound, bound)
        nn.init.uniform_(self.rel.weight, -bound, bound)
        self.normalize()

    @torch.no_grad()
    def normalize(self):
        self.ent.weight.data = nn.functional.normalize(self.ent.weight.data, p=2, dim=-1)

    def dist(self, h, r, t):
        return torch.norm(self.ent(h) + self.rel(r) - self.ent(t), p=self.p, dim=-1)

    def dist_all_tails(self, h, r):
        """(B,) heads, (B,) relations -> (B, n_ent) distances to every entity as tail."""
        q = (self.ent(h) + self.rel(r)).unsqueeze(1)
        return torch.norm(q - self.ent.weight.unsqueeze(0), p=self.p, dim=-1)


class RotatE(nn.Module):
    def __init__(self, n_ent: int, n_rel: int, dim: int = 64, gamma: float = 6.0):
        super().__init__()
        self.dim = dim
        self.ent = nn.Embedding(n_ent, 2 * dim)          # real | imaginary
        self.phase = nn.Embedding(n_rel, dim)
        bound = (gamma + 2.0) / dim
        nn.init.uniform_(self.ent.weight, -bound, bound)
        nn.init.uniform_(self.phase.weight, -math.pi, math.pi)

    def normalize(self):
        pass

    def _rotate(self, h, r):
        hr, hi = torch.chunk(self.ent(h), 2, dim=-1)
        ph = self.phase(r)
        c, s = torch.cos(ph), torch.sin(ph)
        return hr * c - hi * s, hr * s + hi * c

    def dist(self, h, r, t):
        re, im = self._rotate(h, r)
        tr, ti = torch.chunk(self.ent(t), 2, dim=-1)
        d = torch.stack([re - tr, im - ti], dim=0)
        return d.norm(dim=0).sum(dim=-1)

    def dist_all_tails(self, h, r):
        re, im = self._rotate(h, r)
        allr, alli = torch.chunk(self.ent.weight, 2, dim=-1)
        dr = re.unsqueeze(1) - allr.unsqueeze(0)
        di = im.unsqueeze(1) - alli.unsqueeze(0)
        return torch.sqrt(dr * dr + di * di + 1e-12).sum(dim=-1)


def make_model(name: str, n_ent: int, n_rel: int, dim: int, gamma: float):
    if name == "transe":
        return TransE(n_ent, n_rel, dim)
    if name == "rotate":
        return RotatE(n_ent, n_rel, dim, gamma)
    raise ValueError(f"unknown model {name!r}")
