"""Release contracts for the current notebook collection."""
from pathlib import Path
import re

import nbformat
import pytest

ROOT = Path("Notebook")
NAMES = (
    "Project_Overview", "Data_Collection", "Exploratory_Data_Analysis",
    "Data_Cleaning", "Feature_Engineering", "Feature_Selection",
    "Model_Development", "Model_Comparison", "Forecasting", "Trading_Strategies",
    "Logistics_And_Storage", "Multi_Day_Planning", "Application_Integration",
    "Results_And_Conclusions",
)
NOTEBOOKS = [f"{i:02}_{name}.ipynb" for i, name in enumerate(NAMES, 1)]


def test_notebook_inventory_and_readme_links():
    assert sorted(p.name for p in ROOT.glob("*.ipynb")) == NOTEBOOKS
    readme = Path("README.md").read_text(encoding="utf-8")
    assert all(f"(Notebook/{name})" in readme for name in NOTEBOOKS)


@pytest.mark.parametrize("name", NOTEBOOKS)
def test_notebook_release_contract(name):
    book = nbformat.read(ROOT / name, as_version=4)
    nbformat.validate(book)
    code = [cell for cell in book.cells if cell.cell_type == "code"]
    assert code and book.metadata.kernelspec.name == "python3"
    assert all(cell.execution_count for cell in code)
    assert not any(o.output_type == "error" for cell in code for o in cell.outputs)
    source = "\n".join(cell.source for cell in code)
    assert "from mandi_notes import" in source
    assert not re.search(r"[A-Z]:[/\\]|\.secrets|DATAGOV_API_KEY|\.to_parquet\(|\.to_csv\(|run_test\(", source)
