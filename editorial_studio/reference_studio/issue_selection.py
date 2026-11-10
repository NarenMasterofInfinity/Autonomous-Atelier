"""Choose an issue sequence from already rendered, admitted reference adaptations."""

from itertools import product


def select_sequence(compositions):
    choices = [[c for c in run.candidates if c.quality.passed] for run in compositions]
    if any(not candidates for candidates in choices):
        raise ValueError("Every issue slot needs an admitted reference composition")

    def score(sequence):
        families = [c.family_id for c in sequence]
        counts = [families.count(family) for family in set(families)]
        return (
            min(len(counts), 5),
            -sum(a == b for a, b in zip(families, families[1:], strict=False)),
            sum(
                c.program_id == run.selected_program_id
                for c, run in zip(sequence, compositions, strict=True)
            ),
            -sum(count * count for count in counts),
            sum(c.minimum_display_ratio for c in sequence),
        )

    return list(max(product(*choices), key=score))
