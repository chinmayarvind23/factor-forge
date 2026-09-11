# Chronological validation splits

`validation/splits.py` provides expanding walk-forward folds and an explicit
contiguous purged test fold. Inputs are ordered formation groups with label start,
label end and actual label availability timestamps. All securities sharing a
formation clock must belong to the same group. The caller supplies and verifies
these clocks from retained data; the splitter validates metadata chronology.

Walk-forward uses only preceding groups whose labels are available strictly before
the first test formation. `initial_train_size` counts candidate historical groups;
the returned training set can be smaller after availability exclusions. Test blocks
do not overlap, and a final partial block is retained. A fold with no mature training
labels is rejected. Future groups never enter walk-forward training.

Purged cross-validation permits training on both sides of a contiguous test block.
It conservatively excludes every training label intersecting the closed interval
from the first test formation to the latest test label end. This envelope can also
exclude labels lying in internal gaps between test labels. The declared embargo is
elapsed seconds after that latest end; training formations at the embargo endpoint
are excluded. It is not a trading-session count. Zero embargo still purges labels
touching the test boundary. Purging and embargo indices are retained separately.

The functions accept at most 10,000 groups; walk-forward returns at most 100 folds.
They neither fit a model nor grade a factor. Feature selection, transformations and
hyperparameter fitting must use training indices only. Fold metrics need explicit
frequency and comparable evaluation horizons, particularly with irregular groups.
Integrating these folds into retained experiment validation is the next layer.

The general chronological baseline follows the purpose of
[scikit-learn TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html).
The overlap and embargo concepts are described in
[MLFinLab's cross-validation documentation](https://random-docs.readthedocs.io/en/latest/implementations/cross_validation.html).
FactorForge's availability rule, closed boundaries, conservative envelope and
elapsed-second embargo are explicit local policies, not claims of identical library outputs.
