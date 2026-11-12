"""Gender = MEN / WOMEN / KIDS from the product's Men/Women/Child tag, everywhere (Manav, 12 Nov 2026: the VFL
report's gender "doesnt have kids, so it doesnt match the manager gender bifurcation")."""
import pandas as pd

import loader as L


def test_child_is_kids_and_the_tag_decides_not_the_brand_line():
    f = pd.DataFrame({L.COL_DIVISION: ["KURTA SET", "CHILD", "MOHEY-SAREE", "KURTA SET"],
                      "Men/Women/Child": ["MEN", "CHILD", "WOMEN", "WOMEN"]})
    assert list(L.brand_gender(f)) == ["MEN", "KIDS", "WOMEN", "WOMEN"]
    assert L.GENDER_ORDER == ["MEN", "WOMEN", "KIDS"]


def test_without_the_tag_the_old_brand_line_rule_still_answers():
    f = pd.DataFrame({L.COL_DIVISION: ["KURTA SET", "MOHEY-SAREE", "TWAMEV-WOMEN · SAREE"]})
    assert list(L.brand_gender(f)) == ["MEN", "WOMEN", "WOMEN"]
