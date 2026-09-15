# pyright: reportMissingTypeStubs=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from datasets import Dataset, load_dataset

from router.categories import true_category
from router.schema import Category

TEXT_COL = "utterance"
LABEL_COL = "label"


def _id_to_name() -> dict[int, str]:
    intents = load_dataset("DeepPavlov/clinc150", "intents", split="intents")
    assert isinstance(intents, Dataset)
    ids: list[int] = list(intents["id"])
    names: list[str] = list(intents["name"])
    return {int(i): str(n) for i, n in zip(ids, names)}

def load_tasks(n: int, include_other: bool = False) -> list[tuple[str, Category]]:
    id_to_name = _id_to_name()
    ds = load_dataset("DeepPavlov/clinc150", split="test").shuffle(seed=42)
    assert isinstance(ds, Dataset)

    texts: list[str] = list(ds[TEXT_COL])      # column access → list, well-typed
    labels: list[int] = list(ds[LABEL_COL])

    out: list[tuple[str, Category]] = []
    for text, label in zip(texts, labels):
        cat = true_category(id_to_name[int(label)])
        if cat is Category.other and not include_other:
            continue
        out.append((str(text), cat))
        if len(out) >= n:
            break
    return out


__all__ = ["load_tasks"]