"""
dbcheck_core.py
Refactored, UI-friendly core for the dbcheck.py routines.

Notes:
- Logic mirrors the original script (compData / validCollar / validSurvey / validAssay)
  but returns DataFrames and summaries instead of printing / writing files.
- Default behaviour follows the original: numeric differences use abs(delta) > 0.001,
  and NA values are filled with 0 during comparison (script-compatible).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Union

import numpy as np
import pandas as pd


def _build_error_summary(errordf: pd.DataFrame) -> pd.DataFrame:
    """Build standard TYPE + n summary with a stable empty schema."""
    if errordf.empty:
        return pd.DataFrame(columns=["TYPE", "n"])
    return (
        errordf.groupby("TYPE", dropna=False)
        .size()
        .reset_index(name="n")
        .sort_values("n", ascending=False)
    )


@dataclass
class CompareResult:
    col_only_old: List[str]
    col_only_new: List[str]
    additional_records: pd.DataFrame   # keys + DB (old/new)
    differences: pd.DataFrame          # keys + binary flags + *_old / *_new
    diff_counts: pd.DataFrame          # column + n_different
    n_old: int
    n_new: int
    n_match: int


def _normalize_colname(s: str) -> str:
    return "".join(ch for ch in s.strip().lower() if ch.isalnum() or ch == "_")


def suggest_columns(columns: List[str], candidates: List[str]) -> Optional[str]:
    """Return the first matching column name using case/format-insensitive matching."""
    norm_map = {_normalize_colname(c): c for c in columns}
    for cand in candidates:
        key = _normalize_colname(cand)
        if key in norm_map:
            return norm_map[key]
    return None


def _convert_common_types(df_old: pd.DataFrame, df_new: pd.DataFrame, bhid_col: str) -> Tuple[pd.DataFrame, pd.DataFrame, List[str], List[str]]:
    """
    Convert common columns to the most common type in OLD file (matching original compData logic).
    Returns converted (old, new, to_str, to_num).
    """
    common = list(df_old.columns.intersection(df_new.columns))
    to_str: List[str] = []
    to_num: List[str] = []

    for col in common:
        if col == bhid_col:
            continue
        # Majority type based on OLD
        counttypes = df_old[col].apply(type).value_counts()
        majtype = counttypes.index[counttypes.argmax()] if len(counttypes) else object
        if majtype == str:
            to_str.append(col)
        else:
            to_num.append(col)

    # Apply conversions
    def apply(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        if to_str:
            out[to_str] = out[to_str].astype(str)
        if to_num:
            out[to_num] = out[to_num].apply(pd.to_numeric, errors="coerce")
        out[bhid_col] = out[bhid_col].astype(str)
        return out

    return apply(df_old), apply(df_new), to_str, to_num


def compare_data(
    ftype: str,
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    bhid: str,
    at: Optional[str] = None,
    from_i: Optional[str] = None,
    to_i: Optional[str] = None,
    numeric_tolerance: float = 0.001,
    script_compatible_fillna: bool = True,
) -> CompareResult:
    """
    Compare OLD vs NEW dataset for:
      - collar: key = [bhid]
      - survey: key = [bhid, at]
      - assay/litho: key = [bhid, from_i, to_i]
    """

    ftype = ftype.lower().strip()
    if ftype not in {"collar", "survey", "assay", "litho"}:
        raise ValueError("ftype must be one of: collar, survey, assay, litho")

    if ftype == "collar":
        key = [bhid]
    elif ftype == "survey":
        if not at:
            raise ValueError("at is required for survey comparisons")
        key = [bhid, at]
    else:
        if not (from_i and to_i):
            raise ValueError("from_i and to_i are required for assay/litho comparisons")
        key = [bhid, from_i, to_i]

    # Convert shared column types based on OLD (original behaviour)
    df_old, df_new, _, _ = _convert_common_types(df_old, df_new, bhid)

    col_only_old = sorted(list(set(df_old.columns) - set(df_new.columns)))
    col_only_new = sorted(list(set(df_new.columns) - set(df_old.columns)))

    # Additional records (outer merge)
    merge_all = pd.merge(df_old, df_new, how="outer", on=key, indicator=True, copy=False)
    df_add = merge_all.loc[merge_all["_merge"] != "both", key + ["_merge"]].copy()
    df_add.reset_index(drop=True, inplace=True)
    df_add["_merge"] = df_add["_merge"].astype("object").replace({"left_only": "old", "right_only": "new"})
    df_add.rename(columns={"_merge": "DB"}, inplace=True)

    # Differences (inner merge)
    merge_int = pd.merge(df_old, df_new, how="inner", on=key, indicator=True, copy=False)

    if script_compatible_fillna:
        # Original script fills NA with 0 across comparison columns.
        for c in merge_int.columns:
            if merge_int[c].isnull().values.any():
                merge_int[c] = merge_int[c].fillna(0)

    # Identify paired columns by base name to avoid order-related mismatches.
    cols_o = {c[:-2]: c for c in merge_int.columns if c.endswith("_x")}
    cols_n = {c[:-2]: c for c in merge_int.columns if c.endswith("_y")}
    comparable_bases = sorted(set(cols_o).intersection(cols_n))

    df_diff = pd.DataFrame({k: merge_int[k] for k in key})

    for base in comparable_bases:
        colx = cols_o[base]
        coly = cols_n[base]
        sx = merge_int[colx]
        sy = merge_int[coly]

        # If dtypes differ, mark error like original.
        if sx.dtype != sy.dtype:
            df_diff[base] = "ERROR"
            continue

        if sx.dtype == "object":
            cond = (sx.astype(str) != sy.astype(str))
            df_diff[base] = (cond.astype(int))
            if cond.any():
                df_diff.loc[cond, f"{base}_old"] = sx[cond]
                df_diff.loc[cond, f"{base}_new"] = sy[cond]
        else:
            # numeric
            cond = (np.abs(pd.to_numeric(sx, errors="coerce") - pd.to_numeric(sy, errors="coerce")) > numeric_tolerance)
            df_diff[base] = (cond.astype(int))
            if cond.any():
                df_diff.loc[cond, f"{base}_old"] = sx[cond]
                df_diff.loc[cond, f"{base}_new"] = sy[cond]

    # counts
    count_rows = []
    for c in df_diff.columns:
        if c in key or c.endswith("_old") or c.endswith("_new"):
            continue
        if df_diff[c].dtype == "object":
            # 'ERROR' counts as differences in summary
            n = int((df_diff[c] != 0).sum())
        else:
            n = int(df_diff[c].sum())
        count_rows.append((c, n))
    diff_counts = pd.DataFrame(count_rows, columns=["column", "n_different"]).sort_values("n_different", ascending=False)

    return CompareResult(
        col_only_old=col_only_old,
        col_only_new=col_only_new,
        additional_records=df_add,
        differences=df_diff,
        diff_counts=diff_counts,
        n_old=len(df_old),
        n_new=len(df_new),
        n_match=len(merge_int),
    )


@dataclass
class ValidationResult:
    errors: pd.DataFrame
    summary: pd.DataFrame   # TYPE + n
    extra: Dict[str, pd.DataFrame]  # optional computed outputs


def validate_survey(
    df: pd.DataFrame,
    bhid: str,
    at: str,
    azimuth: str,
    dip: str,
    dls_threshold_deg_per_30m: float = 15.0,
    check_duplicates_globally: bool = True,
) -> ValidationResult:
    """
    Mirrors validSurvey:
      1) invalid Dip/Azimuth (dip outside [-90,90] or azimuth outside [-360,360])
      2) null values
      3) duplicated values (AT/AZIMUTH/DIP) - global by default (script behaviour)
      4) DLS > threshold per 30 m
    """
    df = df.copy()
    fields = [bhid, at, azimuth, dip]
    df = df[fields].copy()
    df[bhid] = df[bhid].astype(str)
    df[[at, azimuth, dip]] = df[[at, azimuth, dip]].apply(pd.to_numeric, errors="coerce")
    df.sort_values([bhid, at], inplace=True)

    errors = []

    # 1 invalid values
    cond0 = df[(df[dip] > 90) | (df[dip] < -90) | (df[azimuth] > 360) | (df[azimuth] < -360)].copy()
    if len(cond0):
        cond0["TYPE"] = "invalid Dip/Azimuth"
        errors.append(cond0)

    # 2 nulls
    cond1 = df[df.isnull().any(axis=1)].copy()
    if len(cond1):
        cond1["TYPE"] = "null values"
        errors.append(cond1)

    # 3 duplicates
    if check_duplicates_globally:
        cond2 = df[df[[at, azimuth, dip]].duplicated(keep=False)].copy()
    else:
        cond2 = df[df.duplicated([bhid, at, azimuth, dip], keep=False)].copy()
    if len(cond2):
        cond2["TYPE"] = "duplicated values"
        errors.append(cond2)

    # 4 DLS
    dls = df.copy()
    dls["dip2"] = dls.groupby(bhid)[dip].shift(-1)
    dls["az2"] = dls.groupby(bhid)[azimuth].shift(-1)
    dls["at2"] = dls.groupby(bhid)[at].shift(-1)
    dls["interval"] = dls["at2"] - dls[at]

    # Dogleg severity (same formula as original)
    dls["DLS"] = np.degrees(
        np.arccos(
            np.sin(np.radians(dls[dip])) * np.sin(np.radians(dls["dip2"])) +
            (np.cos(np.radians(dls[dip])) * np.cos(np.radians(dls["dip2"])) * np.cos(np.radians(dls["az2"] - dls[azimuth])))
        )
    ) / dls["interval"] * 30.0

    cond3 = dls[dls["DLS"] > dls_threshold_deg_per_30m][fields + ["DLS"]].copy()
    if len(cond3):
        cond3["TYPE"] = f"DLS > {dls_threshold_deg_per_30m:g} degrees / 30 m"
        errors.append(cond3[fields + ["TYPE", "DLS"]])

    if errors:
        errordf = pd.concat(errors, ignore_index=True)
    else:
        errordf = pd.DataFrame(columns=fields + ["TYPE"])

    summary = _build_error_summary(errordf)

    return ValidationResult(errors=errordf, summary=summary, extra={"survey_dls": dls})


def validate_collar(
    df: pd.DataFrame,
    bhid: str,
    x: str,
    y: str,
    z: str,
) -> ValidationResult:
    """
    Mirrors validCollar:
      1) Zero/Null values
      2) Rounded coordinates (integer)
      3) duplicated Hole ID
      4) duplicated coordinates (XYZ)
      5) inverted X and Y (heuristic)
      6) coordinates to be reviewed (outside mean ± 5 std)
      7) Holeid with spaces on last character
    """
    df = df.copy()
    fields = [bhid, x, y, z]
    collar = df[fields].copy()
    collar[bhid] = collar[bhid].astype(str)

    errors = []

    # 1 zero/null
    cond0 = collar[(collar[x] == 0) | (collar[y] == 0) | (collar[z] == 0) | (collar.isnull().any(axis=1))].copy()
    if len(cond0):
        cond0["TYPE"] = "Zero/Null values"
        errors.append(cond0)

    # 2 rounded coordinates
    # Ensure numeric for modulo; coercing errors to NaN will drop from integer test.
    tmp = collar.copy()
    tmp[[x, y, z]] = tmp[[x, y, z]].apply(pd.to_numeric, errors="coerce")
    cond1 = tmp[(tmp[x] % 1 == 0) & (tmp[y] % 1 == 0) & (tmp[z] % 1 == 0)].copy()
    if len(cond1):
        cond1["TYPE"] = "Rounded coordinates"
        errors.append(cond1)

    # 3 duplicated holeid
    cond2 = collar[collar[bhid].duplicated(keep=False)].copy()
    if len(cond2):
        cond2["TYPE"] = "duplicated Hole ID"
        errors.append(cond2)

    # 4 duplicated coords
    cond3 = collar[collar[[x, y, z]].duplicated(keep=False)].copy()
    if len(cond3):
        cond3["TYPE"] = "duplicated coordinates"
        errors.append(cond3)

    # 5 inverted X/Y heuristic (same as original)
    cx = tmp[x]
    cy = tmp[y]
    cond4 = collar[
        (cx > (cy.mean() - cy.std())) & (cx < (cy.mean() + cy.std())) &
        (cy > (cx.mean() - cx.std())) & (cy < (cx.mean() + cx.std()))
    ].copy()
    if len(cond4):
        cond4["TYPE"] = "inverted X and Y"
        errors.append(cond4)

    # 6 outliers > 5 std
    c1 = (tmp[x] > tmp[x].mean() + 5 * tmp[x].std()) | (tmp[x] < tmp[x].mean() - 5 * tmp[x].std())
    c2 = (tmp[y] > tmp[y].mean() + 5 * tmp[y].std()) | (tmp[y] < tmp[y].mean() - 5 * tmp[y].std())
    c3 = (tmp[z] > tmp[z].mean() + 5 * tmp[z].std()) | (tmp[z] < tmp[z].mean() - 5 * tmp[z].std())
    cond5 = collar[c1 | c2 | c3].copy()
    if len(cond5):
        cond5["TYPE"] = "coordinates to be reviewed"
        errors.append(cond5)

    # 7 trailing spaces
    cond6 = collar[collar[bhid].str[-1:] == " "].copy()
    if len(cond6):
        cond6["TYPE"] = "Holeid with spaces on last character"
        errors.append(cond6)

    if errors:
        errordf = pd.concat(errors, ignore_index=True)
    else:
        errordf = pd.DataFrame(columns=fields + ["TYPE"])

    summary = _build_error_summary(errordf)

    return ValidationResult(errors=errordf, summary=summary, extra={})


def validate_assay(
    df: pd.DataFrame,
    bhid: str,
    from_i: str,
    to_i: str,
    grade_fields: List[str],
    maxes: Union[List[float], np.ndarray],
    sampleid: Optional[str] = None,
) -> ValidationResult:
    """
    Mirrors validAssay:
      1) FROM/TO overlaps (within each hole)
      2) negative/zero values (any grade field <= 0)
      3) unexpected grades (any grade field > maxes[i])
      4) duplicated Sample ID (if provided)
      5) recurring assays (duplicate grade vectors, filtered by SUM>1)
    """
    df = df.copy()
    cols = [bhid, from_i, to_i] + ([sampleid] if sampleid else []) + grade_fields
    assay = df[cols].copy()

    assay[bhid] = assay[bhid].astype(str)
    assay[[from_i, to_i]] = assay[[from_i, to_i]].apply(pd.to_numeric, errors="coerce")
    assay[grade_fields] = assay[grade_fields].apply(pd.to_numeric, errors="coerce")
    assay.sort_values([bhid, from_i, to_i], inplace=True)

    errors = []

    # 1 overlaps
    cond0 = assay.copy()
    cond0["from_i2"] = assay.groupby(bhid)[from_i].shift(-1)
    cond0["to_i2"] = assay.groupby(bhid)[to_i].shift(1)
    cond0 = cond0[(cond0[to_i] > cond0["from_i2"]) | (cond0["to_i2"] > cond0[from_i])]
    cond0 = cond0.drop(columns=["from_i2", "to_i2"])
    if len(cond0):
        cond0["TYPE"] = "FROM/TO overlaps"
        errors.append(cond0)

    # 2 negative/zero
    cond1 = assay[(assay[grade_fields] <= 0).any(axis=1)].copy()
    if len(cond1):
        cond1["TYPE"] = "negative/zero values"
        errors.append(cond1)

    # 3 unexpected grades
    maxes_arr = np.asarray(maxes, dtype=float)
    if maxes_arr.shape[0] != len(grade_fields):
        raise ValueError("maxes must have the same length as grade_fields")
    # Broadcast compare
    cond2 = assay[(assay[grade_fields] > maxes_arr).any(axis=1)].copy()
    if len(cond2):
        cond2["TYPE"] = "unexpected grades"
        errors.append(cond2)

    # 4 duplicated sample id
    if sampleid:
        cond3 = assay[assay[sampleid].duplicated(keep=False)].copy()
        if len(cond3):
            cond3["TYPE"] = "duplicated Sample ID"
            errors.append(cond3)

    # 5 recurring assays
    cond4 = assay.copy().fillna(0)
    cond4["SUM"] = cond4[grade_fields].sum(axis=1)
    cond4 = cond4[(cond4["SUM"].duplicated(keep=False)) & (cond4["SUM"] > 1)]
    cond4 = cond4[cond4[grade_fields].duplicated(keep=False)].sort_values(["SUM"], ascending=True).drop(columns=["SUM"])
    if len(cond4):
        cond4["TYPE"] = "recurring assays"
        errors.append(cond4)

    if errors:
        errordf = pd.concat(errors, ignore_index=True)
    else:
        errordf = pd.DataFrame(columns=cols + ["TYPE"])

    summary = _build_error_summary(errordf)

    return ValidationResult(errors=errordf, summary=summary, extra={})
