"""
MACE (Multi-Annotator Competence Estimation) algorithm implementation.

Implements the Variational Bayes EM algorithm from:
    Hovy, D., Berg-Kirkpatrick, T., Vaswani, A., & Hovy, E. (2013).
    Learning Whom to Trust with MACE. NAACL-HLT.

Each annotator is modeled as either "knowing" (produces correct labels) or
"guessing" (random strategy). The algorithm jointly estimates:
1. True labels for each item (posterior distribution over categories)
2. Annotator competence scores — P(knowing) per annotator (0.0–1.0)

This module has no Potato dependencies and can be used standalone.
"""

import logging

import numpy as np
from scipy.special import digamma

logger = logging.getLogger(__name__)

# Small constant to prevent log(0)
EPS = 1e-10


class MACEAlgorithm:
    """Pure MACE implementation using Variational Bayes EM.

    Args:
        num_annotators: Number of annotators (columns in annotations matrix).
        num_labels: Number of possible label categories.
        num_instances: Number of items (rows in annotations matrix).
        alpha: Beta prior parameter for spamming (competence). Default 0.5.
        beta: Dirichlet prior parameter for guessing strategy. Default 0.5.
        num_restarts: Number of random restarts to find best solution. Default 10.
        num_iters: Number of EM iterations per restart. Default 50.
        seed: Random seed for reproducibility. None for non-deterministic.
    """

    def __init__(
        self,
        num_annotators,
        num_labels,
        num_instances,
        alpha=0.5,
        beta=0.5,
        num_restarts=10,
        num_iters=50,
        seed=None,
    ):
        self.num_annotators = num_annotators
        self.num_labels = num_labels
        self.num_instances = num_instances
        self.alpha = alpha
        self.beta = beta
        self.num_restarts = num_restarts
        self.num_iters = num_iters
        self.rng = np.random.RandomState(seed)

    def fit(self, annotations):
        """Run MACE on an annotation matrix.

        Args:
            annotations: np.ndarray of shape (num_instances, num_annotators).
                Values are label indices 0..num_labels-1, or -1 for missing.

        Returns:
            tuple: (predicted_labels, competence, marginals, log_likelihood)
                - predicted_labels: np.ndarray of shape (num_instances,), argmax label per item
                - competence: np.ndarray of shape (num_annotators,), P(knowing) per annotator
                - marginals: np.ndarray of shape (num_instances, num_labels), posterior over labels
                - log_likelihood: float, log-likelihood of the best restart
        """
        best_ll = -np.inf
        best_result = None

        for restart in range(self.num_restarts):
            spamming, theta = self._initialize()

            for iteration in range(self.num_iters):
                # E-step: compute posterior over true labels
                marginals = self._e_step(annotations, spamming, theta)

                # M-step: update spamming and theta via variational update
                spamming, theta = self._m_step(annotations, marginals)

            ll = self._log_likelihood(annotations, marginals, spamming, theta)

            if ll > best_ll:
                best_ll = ll
                best_result = (marginals, spamming, theta)

        marginals, spamming, theta = best_result

        # Decode: argmax of marginals
        predicted_labels = np.argmax(marginals, axis=1)

        # Competence: E[spamming[:,0]] = P(knowing) per annotator
        # spamming[:,0] is the "knowing" component, spamming[:,1] is "guessing"
        competence = spamming[:, 0] / (spamming[:, 0] + spamming[:, 1])

        return predicted_labels, competence, marginals, best_ll

    def _initialize(self):
        """Random initialization of parameters.

        Returns:
            tuple: (spamming, theta)
                - spamming: np.ndarray shape (num_annotators, 2), Beta variational params
                  Column 0 = "knowing" mass, Column 1 = "guessing" mass
                - theta: np.ndarray shape (num_annotators, num_labels), Dirichlet params
                  for guessing strategy per annotator
        """
        # Initialize spamming from Beta(alpha, alpha) prior
        # Add random perturbation to break symmetry
        spamming = np.zeros((self.num_annotators, 2))
        spamming[:, 0] = self.alpha + self.rng.random(self.num_annotators)
        spamming[:, 1] = self.alpha + self.rng.random(self.num_annotators)

        # Initialize theta (guessing strategy) from Dirichlet(beta,...,beta)
        theta = np.zeros((self.num_annotators, self.num_labels))
        for j in range(self.num_annotators):
            theta[j] = self.beta + self.rng.random(self.num_labels)

        return spamming, theta

    def _e_step(self, annotations, spamming, theta):
        """Compute posterior P(true_label=k | observations) for each item.

        Uses the current spamming and theta parameters to compute the
        expected true label distribution via Bayes rule.

        Args:
            annotations: np.ndarray shape (num_instances, num_annotators), -1 = missing
            spamming: np.ndarray shape (num_annotators, 2)
            theta: np.ndarray shape (num_annotators, num_labels)

        Returns:
            marginals: np.ndarray shape (num_instances, num_labels)
        """
        marginals = np.zeros((self.num_instances, self.num_labels))

        # Precompute expected log parameters using digamma
        # E[log spamming_j] for knowing vs guessing
        e_log_s = digamma(spamming) - digamma(spamming.sum(axis=1, keepdims=True))
        # e_log_s[:, 0] = E[log P(knowing)]
        # e_log_s[:, 1] = E[log P(guessing)]

        # E[log theta_j_k] for each annotator's guessing distribution
        e_log_theta = digamma(theta) - digamma(theta.sum(axis=1, keepdims=True))

        for k in range(self.num_labels):
            log_prob = np.zeros(self.num_instances)

            for j in range(self.num_annotators):
                # Mask for instances where annotator j provided a label
                observed = annotations[:, j] >= 0
                if not np.any(observed):
                    continue

                label_j = annotations[observed, j].astype(int)

                # P(observation | knowing, true_label=k):
                #   = 1 if label_j == k, else 0
                # In log space: log(P(knowing) * I(label==k) + P(guessing) * theta[j,label])
                # We use the variational decomposition:
                #   log P(x_ij | T_i=k) = log(exp(E[log s_j0]) * I(a_ij=k)
                #                              + exp(E[log s_j1]) * exp(E[log theta_j,a_ij]))

                # For numerical stability, compute in log-sum-exp form
                knowing_term = np.full(observed.sum(), -np.inf)
                match = label_j == k
                knowing_term[match] = e_log_s[j, 0]

                # Guessing term: P(guessing) * theta[j, observed_label]
                guessing_term = e_log_s[j, 1] + e_log_theta[j, label_j]

                # log-sum-exp of knowing and guessing
                max_term = np.maximum(knowing_term, guessing_term)
                log_sum = max_term + np.log(
                    np.exp(knowing_term - max_term) + np.exp(guessing_term - max_term) + EPS
                )

                log_prob[observed] += log_sum

            marginals[:, k] = log_prob

        # Normalize to probabilities (softmax over labels)
        max_marginals = marginals.max(axis=1, keepdims=True)
        marginals = np.exp(marginals - max_marginals)
        row_sums = marginals.sum(axis=1, keepdims=True)
        row_sums = np.maximum(row_sums, EPS)
        marginals /= row_sums

        return marginals

    def _m_step(self, annotations, marginals):
        """Variational M-step: update spamming and theta using expected counts.

        Args:
            annotations: np.ndarray shape (num_instances, num_annotators), -1 = missing
            marginals: np.ndarray shape (num_instances, num_labels)

        Returns:
            tuple: (spamming, theta) updated parameters
        """
        spamming = np.zeros((self.num_annotators, 2))
        theta = np.zeros((self.num_annotators, self.num_labels))

        for j in range(self.num_annotators):
            observed = annotations[:, j] >= 0
            if not np.any(observed):
                # No observations for this annotator — use prior
                spamming[j, 0] = self.alpha
                spamming[j, 1] = self.alpha
                theta[j] = self.beta
                continue

            label_j = annotations[observed, j].astype(int)
            marginals_j = marginals[observed]

            # Expected count of "knowing" for annotator j:
            # Sum over instances where annotator's label matches true label
            # weighted by P(true_label=k)
            knowing_count = 0.0
            guessing_count = 0.0

            for i_idx in range(len(label_j)):
                k = label_j[i_idx]
                p_correct = marginals_j[i_idx, k]
                knowing_count += p_correct
                guessing_count += (1.0 - p_correct)

            spamming[j, 0] = self.alpha + knowing_count
            spamming[j, 1] = self.alpha + guessing_count

            # Update theta: expected count of guessing label k
            # When guessing, the annotator produces label a_ij with probability theta[j, a_ij]
            # The expected count of guessing-and-producing-label-k is:
            # sum_i (1 - P(knowing_ij)) * I(a_ij = k)
            for k in range(self.num_labels):
                mask = label_j == k
                if np.any(mask):
                    # Weight by P(guessing) ≈ 1 - P(correct)
                    theta[j, k] = self.beta + np.sum(1.0 - marginals_j[mask, k])
                else:
                    theta[j, k] = self.beta

        return spamming, theta

    def _log_likelihood(self, annotations, marginals, spamming, theta):
        """Compute log-likelihood of the data given current parameters.

        Args:
            annotations: np.ndarray shape (num_instances, num_annotators)
            marginals: np.ndarray shape (num_instances, num_labels)
            spamming: np.ndarray shape (num_annotators, 2)
            theta: np.ndarray shape (num_annotators, num_labels)

        Returns:
            float: log-likelihood value
        """
        ll = 0.0

        # Normalize spamming and theta to probabilities for likelihood
        s_norm = spamming / spamming.sum(axis=1, keepdims=True)
        t_norm = theta / theta.sum(axis=1, keepdims=True)

        for i in range(self.num_instances):
            for k in range(self.num_labels):
                if marginals[i, k] < EPS:
                    continue

                log_p = 0.0
                for j in range(self.num_annotators):
                    if annotations[i, j] < 0:
                        continue
                    a = int(annotations[i, j])

                    # P(a_ij | T_i=k) = s_j * I(a==k) + (1-s_j) * theta_j_a
                    p_knowing = s_norm[j, 0] * (1.0 if a == k else 0.0)
                    p_guessing = s_norm[j, 1] * t_norm[j, a]
                    p = p_knowing + p_guessing
                    log_p += np.log(max(p, EPS))

                ll += marginals[i, k] * log_p

        return ll

    @staticmethod
    def entropy(marginals):
        """Compute entropy of label distributions per item.

        Higher entropy = more uncertainty about the true label.

        Args:
            marginals: np.ndarray shape (num_instances, num_labels)

        Returns:
            np.ndarray shape (num_instances,), entropy per item
        """
        # Clip to avoid log(0)
        p = np.clip(marginals, EPS, 1.0)
        return -np.sum(p * np.log(p), axis=1)
