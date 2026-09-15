from datasets import load_dataset, Dataset
from typing import Any,cast

from router.categories import true_category
from router.schema import Category

TEXT_COL = "utterance"
LABEL_COL = "label"

""" print(ds)                    # splits + features
print(ds.features)           # {'utterance': Value('string'), 'label': Value('int64')}
print(ds[0])                 # one row
print(ds.num_rows, "rows")

print(intents[0])            # {'id': 0, 'name': '...', ...}
 """
def _id_to_name() -> dict[int, str]:
    intents = load_dataset("DeepPavlov/clinc150", "intents", split="intents")
    return dict(zip(intents["id"], intents["name"]))

def load_tasks(n: int, include_other: bool = False) -> list[tuple[str,Category]]:
  id_to_name = _id_to_name()
  ds = load_dataset("DeepPavlov/clinic150", split="test").shuffle(seed=42)
  out: list[tuple[str,Category]] = []
  for row in ds:
    row = cast(dict[str,Any],row)
    intent = id_to_name[row[LABEL_COL]]
    cat=true_category(intent)
    if cat is Category.other and not include_other:
      continue
    out.append((row[TEXT_COL],cat))
    if len(out) >= n:
      break;

  return out;

    

__all__ = ["load_tasks"]