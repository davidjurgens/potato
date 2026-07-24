"""
Item response theory for annotation: joint inference of true labels,
annotator ability, and item difficulty — no gold labels, no LLM.

The model is a multiclass generalization of GLAD (Whitehill et al., NeurIPS
2009). Each annotation is modeled as:

    P(annotator j labels item i correctly) = sigmoid(alpha_j * exp(b_i))

where ``alpha_j`` is annotator ability (higher = better; 0 = uninformative;
negative = systematically wrong) and ``b_i`` is item *easiness* on a log
scale (reported as difficulty = -b_i, higher = harder). Incorrect responses
are spread uniformly over the remaining K-1 labels. The latent true label
``z_i`` and the parameters are fit jointly by EM:

- E-step: posterior over each item's true label given current parameters
- M-step: L-BFGS on the expected penalized log-likelihood (analytic
  gradients), with Gaussian priors alpha ~ N(1, var) and b ~ N(0, var) for
  identifiability on sparse data

Because agreement patterns alone drive the fit, the model recovers *who is
reliable* and *which items are hard* from raw annotations. Byproducts:

- Per-label posterior probabilities (labels with error bars): the MAP label,
  its posterior probability, and a +/-1 SE ability-sensitivity band
- Per-annotator ability with an approximate standard error (Fisher
  information at the mode, treating label posteriors as fixed)
- Per-item difficulty, and a *discrimination* diagnostic: the correlation
  between annotator ability and answer correctness on that item. Strongly
  negative discrimination means your best annotators disagree with the
  crowd consensus — almost always a codebook bug, not an annotator problem.
- Exact one-step expected information gain for (item, annotator) pairs,
  which powers adaptive routing.

The fit is deterministic (no random initialization) and fast: EM refits in
milliseconds at annotation-study scale, so the engine can refit live as
labels stream in.
"""

import logging
import math
from dataclasses import dataclass, field
from typing import Any, Dict, Hashable, List, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import minimize
from scipy.special import expit, logsumexp

logger = logging.getLogger(__name__)

# Numerical floors/ceilings for probabilities inside logs.
_P_MIN = 1e-9
_P_MAX = 1.0 - 1e-9


@dataclass
class AbilityEstimate:
    """Fitted ability for one annotator.

    Attributes:
        theta: Ability estimate (1.0 is the prior mean; 0 = uninformative;
            negative = adversarial/systematically inverted).
        se: Approximate standard error (Fisher information at the mode).
        n_labels: Number of annotations this annotator contributed to the fit.
    """

    theta: float
    se: float
    n_labels: int


@dataclass
class ItemEstimate:
    """Fitted results for one item.

    Attributes:
        map_label: Most probable true label under the posterior.
        prob: Posterior probability of ``map_label``.
        prob_lo / prob_hi: +/-1 SE ability-sensitivity band on ``prob``.
        entropy: Posterior entropy in bits (0 = certain).
        difficulty: -b_i; higher = harder. 0 is the prior mean.
        discrimination: Correlation between annotator ability and answer
            correctness on this item (None if < 3 annotators or degenerate).
        n_annotators: Number of annotations on this item.
        flagged: True when discrimination is strongly negative — the
            "codebook bug" signal (best annotators lose to the crowd).
        posterior: Full label -> probability distribution.
    """

    map_label: Any
    prob: float
    prob_lo: float
    prob_hi: float
    entropy: float
    difficulty: float
    discrimination: Optional[float]
    n_annotators: int
    flagged: bool
    posterior: Dict[Any, float] = field(default_factory=dict)


def _entropy_bits(p: np.ndarray, axis: int = -1) -> np.ndarray:
    """Shannon entropy in bits along ``axis``; safe at p=0."""
    q = np.clip(p, _P_MIN, 1.0)
    return -np.sum(p * np.log2(q), axis=axis)


class IRTModel:
    """Multiclass GLAD fit over a set of (item, annotator, label) observations.

    A model instance is fit once over a snapshot of observations; the live
    engine re-fits a fresh instance as new labels arrive (fits are cheap and
    deterministic). One model covers one annotation scheme.
    """

    def __init__(
        self,
        prior_ability_mean: float = 1.0,
        prior_ability_var: float = 1.0,
        prior_difficulty_var: float = 1.0,
        max_em_iters: int = 50,
        m_step_maxiter: int = 50,
        tol: float = 1e-5,
        discrimination_flag_threshold: float = -0.2,
    ):
        self.prior_ability_mean = float(prior_ability_mean)
        self.prior_ability_var = float(prior_ability_var)
        self.prior_difficulty_var = float(prior_difficulty_var)
        self.max_em_iters = int(max_em_iters)
        self.m_step_maxiter = int(m_step_maxiter)
        self.tol = float(tol)
        self.discrimination_flag_threshold = float(discrimination_flag_threshold)

        self.fitted: bool = False
        self.degenerate_reason: Optional[str] = None
        self.class_labels: List[Any] = []
        self.log_likelihood: float = float("nan")
        self.em_iterations: int = 0

        self._item_ids: List[Hashable] = []
        self._ann_ids: List[Hashable] = []
        self._item_index: Dict[Hashable, int] = {}
        self._ann_index: Dict[Hashable, int] = {}
        self._label_index: Dict[Any, int] = {}
        # Observation arrays (deduped, last write wins per (item, annotator)).
        self._obs_item: np.ndarray = np.empty(0, dtype=np.int64)
        self._obs_ann: np.ndarray = np.empty(0, dtype=np.int64)
        self._obs_label: np.ndarray = np.empty(0, dtype=np.int64)
        # Fitted parameters.
        self._alpha: np.ndarray = np.empty(0)
        self._alpha_se: np.ndarray = np.empty(0)
        self._b: np.ndarray = np.empty(0)
        self._log_class_prior: np.ndarray = np.empty(0)
        self._q: np.ndarray = np.empty((0, 0))  # item x class posteriors
        self._q_lo: np.ndarray = np.empty((0, 0))
        self._q_hi: np.ndarray = np.empty((0, 0))
        self._discrimination: Dict[int, Optional[float]] = {}

    # ------------------------------------------------------------------
    # Fitting
    # ------------------------------------------------------------------

    def fit(
        self, observations: Sequence[Tuple[Hashable, Hashable, Any]]
    ) -> "IRTModel":
        """Fit the model on (item_id, annotator_id, label) triples.

        Duplicate (item, annotator) pairs keep the most recent label.
        Returns self. If the data are degenerate (fewer than two distinct
        labels, or no observations), the model is marked unfitted with
        ``degenerate_reason`` set and all report methods degrade gracefully.
        """
        latest: Dict[Tuple[Hashable, Hashable], Any] = {}
        for item_id, ann_id, label in observations:
            latest[(item_id, ann_id)] = label

        if not latest:
            self.degenerate_reason = "no observations"
            return self

        labels = sorted({v for v in latest.values()}, key=repr)
        if len(labels) < 2:
            self.degenerate_reason = "fewer than two distinct labels"
            return self

        self.class_labels = labels
        self._label_index = {lab: k for k, lab in enumerate(labels)}
        self._item_ids = sorted({i for (i, _) in latest}, key=repr)
        self._ann_ids = sorted({a for (_, a) in latest}, key=repr)
        self._item_index = {i: idx for idx, i in enumerate(self._item_ids)}
        self._ann_index = {a: idx for idx, a in enumerate(self._ann_ids)}

        n_obs = len(latest)
        self._obs_item = np.empty(n_obs, dtype=np.int64)
        self._obs_ann = np.empty(n_obs, dtype=np.int64)
        self._obs_label = np.empty(n_obs, dtype=np.int64)
        for n, ((item_id, ann_id), label) in enumerate(sorted(latest.items(), key=repr)):
            self._obs_item[n] = self._item_index[item_id]
            self._obs_ann[n] = self._ann_index[ann_id]
            self._obs_label[n] = self._label_index[label]

        I, J, K = len(self._item_ids), len(self._ann_ids), len(labels)

        # Deterministic initialization at the prior means.
        alpha = np.full(J, self.prior_ability_mean, dtype=np.float64)
        b = np.zeros(I, dtype=np.float64)
        self._log_class_prior = np.full(K, -math.log(K))

        prev_ll = -np.inf
        for em_iter in range(1, self.max_em_iters + 1):
            q, ll = self._e_step(alpha, b)
            # Update class prior from posteriors (Laplace-smoothed).
            prior = (q.sum(axis=0) + 1.0) / (I + K)
            self._log_class_prior = np.log(prior)

            alpha, b = self._m_step(q, alpha, b)

            self.em_iterations = em_iter
            if abs(ll - prev_ll) < self.tol * max(1.0, abs(ll)):
                prev_ll = ll
                break
            prev_ll = ll

        # Final E-step at the converged parameters.
        self._q, self.log_likelihood = self._e_step(alpha, b)
        self._alpha, self._b = alpha, b
        self._alpha_se = self._ability_standard_errors(alpha, b)
        self._q_lo, self._q_hi = self._sensitivity_band(alpha, b)
        self._discrimination = self._discrimination_by_item()
        self.fitted = True
        logger.debug(
            "IRT fit: %d items, %d annotators, %d obs, K=%d, %d EM iters, ll=%.2f",
            I, J, n_obs, K, self.em_iterations, self.log_likelihood,
        )
        return self

    def _correct_prob(self, alpha: np.ndarray, b: np.ndarray) -> np.ndarray:
        """P(correct) per observation, clipped away from 0/1."""
        x = alpha[self._obs_ann] * np.exp(b[self._obs_item])
        return np.clip(expit(np.clip(x, -30.0, 30.0)), _P_MIN, _P_MAX)

    def _e_step(
        self, alpha: np.ndarray, b: np.ndarray
    ) -> Tuple[np.ndarray, float]:
        """Posterior over true labels; returns (q [I x K], observed-data ll)."""
        I = len(self._item_ids)
        K = len(self.class_labels)
        s = self._correct_prob(alpha, b)
        log_s = np.log(s)
        log_w = np.log1p(-s) - math.log(K - 1)

        # log q_i(k) = log prior(k) + sum_obs(i) [k == y ? log_s : log_w]
        #            = log prior(k) + base_i + sum_{obs(i): y=k} (log_s - log_w)
        base = np.zeros(I)
        np.add.at(base, self._obs_item, log_w)
        logq = np.tile(self._log_class_prior, (I, 1)) + base[:, None]
        np.add.at(logq, (self._obs_item, self._obs_label), log_s - log_w)

        norm = logsumexp(logq, axis=1)
        q = np.exp(logq - norm[:, None])
        return q, float(norm.sum())

    def _m_step(
        self, q: np.ndarray, alpha0: np.ndarray, b0: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Maximize the expected penalized log-likelihood via L-BFGS."""
        J, I = len(self._ann_ids), len(self._item_ids)
        # Probability that each observation's given label is the true label.
        q_obs = q[self._obs_item, self._obs_label]
        obs_item, obs_ann = self._obs_item, self._obs_ann
        mu_a, va = self.prior_ability_mean, self.prior_ability_var
        vb = self.prior_difficulty_var

        def objective(params: np.ndarray) -> Tuple[float, np.ndarray]:
            alpha, b = params[:J], params[J:]
            e = np.exp(b[obs_item])
            x = np.clip(alpha[obs_ann] * e, -30.0, 30.0)
            s = np.clip(expit(x), _P_MIN, _P_MAX)
            # Expected complete-data ll (dropping the constant K-1 spread term).
            ll = np.sum(q_obs * np.log(s) + (1.0 - q_obs) * np.log1p(-s))
            ll -= np.sum((alpha - mu_a) ** 2) / (2.0 * va)
            ll -= np.sum(b ** 2) / (2.0 * vb)

            resid = q_obs - s
            g_alpha = np.zeros(J)
            np.add.at(g_alpha, obs_ann, e * resid)
            g_alpha -= (alpha - mu_a) / va
            g_b = np.zeros(I)
            np.add.at(g_b, obs_item, alpha[obs_ann] * e * resid)
            g_b -= b / vb
            return -ll, -np.concatenate([g_alpha, g_b])

        x0 = np.concatenate([alpha0, b0])
        result = minimize(
            objective,
            x0,
            jac=True,
            method="L-BFGS-B",
            options={"maxiter": self.m_step_maxiter},
        )
        params = result.x
        return params[:J], params[J:]

    def _ability_standard_errors(
        self, alpha: np.ndarray, b: np.ndarray
    ) -> np.ndarray:
        """Approximate SEs from Fisher information at the mode.

        Treats label posteriors as fixed (ignores z/parameter coupling), so
        these are mild underestimates — documented as approximate.
        """
        s = self._correct_prob(alpha, b)
        e = np.exp(b[self._obs_item])
        info = np.zeros(len(self._ann_ids))
        np.add.at(info, self._obs_ann, (e ** 2) * s * (1.0 - s))
        info += 1.0 / self.prior_ability_var
        return 1.0 / np.sqrt(info)

    def _sensitivity_band(
        self, alpha: np.ndarray, b: np.ndarray
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Envelope of posteriors under +/-1 SE perturbations of all abilities."""
        q_lo = np.array(self._q, copy=True)
        q_hi = np.array(self._q, copy=True)
        for shifted in (alpha - self._alpha_se_for(alpha, b), alpha + self._alpha_se_for(alpha, b)):
            q, _ = self._e_step(shifted, b)
            q_lo = np.minimum(q_lo, q)
            q_hi = np.maximum(q_hi, q)
        return q_lo, q_hi

    def _alpha_se_for(self, alpha: np.ndarray, b: np.ndarray) -> np.ndarray:
        if self._alpha_se.size == len(alpha):
            return self._alpha_se
        return self._ability_standard_errors(alpha, b)

    def _discrimination_by_item(self) -> Dict[int, Optional[float]]:
        """Ability-vs-correctness correlation per item (>=3 annotators)."""
        q_obs = self._q[self._obs_item, self._obs_label]
        by_item: Dict[int, List[Tuple[float, float]]] = {}
        for n in range(len(self._obs_item)):
            by_item.setdefault(int(self._obs_item[n]), []).append(
                (float(self._alpha[self._obs_ann[n]]), float(q_obs[n]))
            )
        out: Dict[int, Optional[float]] = {}
        for i, pairs in by_item.items():
            if len(pairs) < 3:
                out[i] = None
                continue
            a = np.array([p[0] for p in pairs])
            c = np.array([p[1] for p in pairs])
            if a.std() < 1e-9 or c.std() < 1e-9:
                out[i] = None
                continue
            out[i] = float(np.corrcoef(a, c)[0, 1])
        return out

    # ------------------------------------------------------------------
    # Reports
    # ------------------------------------------------------------------

    @property
    def num_observations(self) -> int:
        return int(self._obs_item.size)

    @property
    def num_items(self) -> int:
        return len(self._item_ids)

    @property
    def num_annotators(self) -> int:
        return len(self._ann_ids)

    def ability(self, annotator_id: Hashable) -> Optional[AbilityEstimate]:
        """Fitted ability for one annotator (None if unknown/unfitted)."""
        if not self.fitted or annotator_id not in self._ann_index:
            return None
        j = self._ann_index[annotator_id]
        return AbilityEstimate(
            theta=float(self._alpha[j]),
            se=float(self._alpha_se[j]),
            n_labels=int(np.sum(self._obs_ann == j)),
        )

    def abilities(self) -> Dict[Hashable, AbilityEstimate]:
        """All annotator abilities, keyed by annotator id."""
        return {a: self.ability(a) for a in self._ann_ids} if self.fitted else {}

    def posterior(self, item_id: Hashable) -> Optional[Dict[Any, float]]:
        """Full label -> probability posterior for one item."""
        if not self.fitted or item_id not in self._item_index:
            return None
        row = self._q[self._item_index[item_id]]
        return {lab: float(row[k]) for k, lab in enumerate(self.class_labels)}

    def item_report(self, item_id: Hashable) -> Optional[ItemEstimate]:
        """Fitted estimates for one item (None if unknown/unfitted)."""
        if not self.fitted or item_id not in self._item_index:
            return None
        i = self._item_index[item_id]
        row = self._q[i]
        k = int(np.argmax(row))
        disc = self._discrimination.get(i)
        return ItemEstimate(
            map_label=self.class_labels[k],
            prob=float(row[k]),
            prob_lo=float(self._q_lo[i, k]),
            prob_hi=float(self._q_hi[i, k]),
            entropy=float(_entropy_bits(row)),
            difficulty=float(-self._b[i]),
            discrimination=disc,
            n_annotators=int(np.sum(self._obs_item == i)),
            flagged=(
                disc is not None and disc < self.discrimination_flag_threshold
            ),
            posterior={lab: float(row[kk]) for kk, lab in enumerate(self.class_labels)},
        )

    def items(self) -> Dict[Hashable, ItemEstimate]:
        """All item reports, keyed by item id."""
        return {i: self.item_report(i) for i in self._item_ids} if self.fitted else {}

    def item_ids(self) -> List[Hashable]:
        return list(self._item_ids)

    def annotator_ids(self) -> List[Hashable]:
        return list(self._ann_ids)

    # ------------------------------------------------------------------
    # Adaptive routing support
    # ------------------------------------------------------------------

    def expected_information_gain(
        self, item_id: Hashable, annotator_id: Hashable
    ) -> float:
        """Exact one-step expected reduction (bits) in an item's label
        entropy if this annotator labels it now.

        Unseen items use the class prior at prior difficulty; unseen
        annotators use the prior-mean ability. Returns 0.0 when unfitted.
        """
        if not self.fitted:
            return 0.0
        K = len(self.class_labels)
        if item_id in self._item_index:
            i = self._item_index[item_id]
            q = self._q[i]
            easiness = math.exp(self._b[i])
        else:
            q = np.exp(self._log_class_prior)
            easiness = 1.0
        theta = (
            float(self._alpha[self._ann_index[annotator_id]])
            if annotator_id in self._ann_index
            else self.prior_ability_mean
        )
        s = float(np.clip(expit(np.clip(theta * easiness, -30.0, 30.0)), _P_MIN, _P_MAX))

        # Response likelihood matrix: P(response l | truth k)
        lik = np.full((K, K), (1.0 - s) / (K - 1))
        np.fill_diagonal(lik, s)
        pred = q @ lik  # P(response l)
        post = (q[:, None] * lik) / np.clip(pred[None, :], _P_MIN, None)  # k x l
        expected_h = float(np.sum(pred * _entropy_bits(post, axis=0)))
        return max(0.0, float(_entropy_bits(q)) - expected_h)
