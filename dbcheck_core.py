from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd


def read_csv_uploaded(uploaded_file) -> pd.DataFrame:
    """
    Reads a Streamlit uploaded CSV with a robust encoding fallback.
    """
    data = uploaded_file.getvalue()
    for enc in ("utf-8", "ISO-8859-1", "latin1"):
        try:
            return pd.read_csv(pd.io.common.BytesIO(data), encoding=enc)
        except Exception:
            continue
    # last resort
    return pd.read_csv(pd.io.common.BytesIO(data), encoding_errors="ignore")


def _coerce_shared_column_types(df_old: pd.DataFrame, df_new: pd.DataFrame, bhid: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Mimics the original script: for columns present in both, coerce types based on OLD majority type.
    """
    df_old = df_old.copy()
    df_new = df_new.copy()

    shared = [c for c in df_old.columns if c in df_new.columns]
    to_str: List[str] = []
    to_num: List[str] = []

    for col in shared:
        if col == bhid:
            continue
        counts = df_old[col].apply(type).value_counts(dropna=False)
        if len(counts) == 0:
            continue
        maj_type = counts.index[counts.argmax()]
        if maj_type == str:
            to_str.append(col)
        else:
            to_num.append(col)

    if to_str:
        df_old[to_str] = df_old[to_str].astype(str)
        df_new[to_str] = df_new[to_str].astype(str)
    if to_num:
        df_old[to_num] = df_old[to_num].apply(pd.to_numeric, errors="coerce")
        df_new[to_num] = df_new[to_num].apply(pd.to_numeric, errors="coerce")

    return df_old, df_new


def compare_data(
    ftype: str,
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    bhid: str,
    at: Optional[str] = None,
    from_i: Optional[str] = None,
    to_i: Optional[str] = None,
    tol: float = 0.001,
    compat_fillna: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Compare OLD vs NEW similar to compData() in the original script.
    Returns:
      - additional_rows: rows present only in one file (DB=old/new)
      - diff_table: binary diff + old/new values where diff
      - diff_counts: per-column diff counts
      - summary: dict with key metrics
    """
    ftype = ftype.lower().strip()
    df_old = df_old.copy()
    df_new = df_new.copy()

    # BHID as string
    if bhid not in df_old.columns or bhid not in df_new.columns:
        raise ValueError(f"BHID column '{bhid}' must exist in both files.")
    df_old[bhid] = df_old[bhid].astype(str)
    df_new[bhid] = df_new[bhid].astype(str)

    # Coerce shared types (script behavior)
    df_old, df_new = _coerce_shared_column_types(df_old, df_new, bhid=bhid)

    # Keys by ftype
    if ftype == "collar":
        key = [bhid]
    elif ftype == "survey":
        if not at:
            raise ValueError("Survey comparison requires 'at' column.")
        key = [bhid, at]
    elif ftype in ("assay", "litho"):
        if not from_i or not to_i:
            raise ValueError("Assay/Litho comparison requires 'from_i' and 'to_i' columns.")
        key = [bhid, from_i, to_i]
    else:
        raise ValueError("ftype must be one of: collar, survey, assay, litho")

    for k in key:
        if k not in df_old.columns or k not in df_new.columns:
            raise ValueError(f"Key column '{k}' must exist in both files.")

    # Additional records (outer merge)
    merge_all = pd.merge(df_old, df_new, how="outer", on=key, indicator=True, copy=False)
    df_add = merge_all.loc[merge_all["_merge"] != "both", key + ["_merge"]].copy()
    df_add.reset_index(drop=True, inplace=True)
    df_add["_merge"] = df_add["_merge"].replace({"left_only": "old", "right_only": "new"})
    df_add.rename(columns={"_merge": "DB"}, inplace=True)

    # fillna(0) in merged tables if compat
    if compat_fillna:
        for c in merge_all.columns:
            if merge_all[c].isnull().any():
                merge_all[c].fillna(0, inplace=True)

    # Intersection merge for value comparison
    merge_int = pd.merge(df_old, df_new, how="inner", on=key, suffixes=("_old", "_new"), copy=False)
    if compat_fillna:
        for c in merge_int.columns:
            if merge_int[c].isnull().any():
                merge_int[c].fillna(0, inplace=True)

    # Determine comparable pairs
    cols_old = sorted([c for c in merge_int.columns if c.endswith("_old")])
    cols_new = sorted([c for c in merge_int.columns if c.endswith("_new")])

    # Build diff table
    df_diff = pd.DataFrame({k: merge_int[k] for k in key})

    for c_old in cols_old:
        base = c_old[:-4]  # strip _old
        c_new = base + "_new"
        if c_new not in merge_int.columns:
            continue

        s_old = merge_int[c_old]
        s_new = merge_int[c_new]

        if s_old.dtype != s_new.dtype:
            # if mismatch, mark error
            df_diff[base] = "ERROR"
            continue

        if s_old.dtype == "object":
            cond = (s_old.astype(str) != s_new.astype(str))
        else:
            cond = (np.abs(pd.to_numeric(s_old, errors="coerce") - pd.to_numeric(s_new, errors="coerce")) > float(tol))

        df_diff[base] = cond.astype(int)
        if cond.any():
            df_diff.loc[cond, base + "_old"] = s_old[cond]
            df_diff.loc[cond, base + "_new"] = s_new[cond]

    # Counts per diff column
    diff_cols = [c for c in df_diff.columns if c not in key and not c.endswith("_old") and not c.endswith("_new")]
    counts = []
    for c in diff_cols:
        if df_diff[c].dtype == "object":
            continue
        counts.append((c, int(df_diff[c].sum())))
    df_counts = pd.DataFrame(counts, columns=["COLUMN", "DIFF_COUNT"]).sort_values("DIFF_COUNT", ascending=False).reset_index(drop=True)

    # records with any differences
    if diff_cols:
        numeric_cols = [c for c in diff_cols if pd.api.types.is_numeric_dtype(df_diff[c])]
        rec_with_diff = int((df_diff[numeric_cols].sum(axis=1) > 0).sum()) if numeric_cols else 0
    else:
        rec_with_diff = 0

    summary = {
        "old_unique": int((df_add["DB"] == "old").sum()),
        "new_unique": int((df_add["DB"] == "new").sum()),
        "matches": int(len(merge_int)),
        "records_with_differences": int(rec_with_diff),
    }

    return {
        "additional_rows": df_add,
        "diff_table": df_diff,
        "diff_counts": df_counts,
        "summary": summary,
    }


def _summary_by_type(issues: pd.DataFrame) -> pd.DataFrame:
    if issues is None or len(issues) == 0:
        return pd.DataFrame(columns=["TYPE", "n"])
    out = issues["TYPE"].astype(str).value_counts().reset_index()
    out.columns = ["TYPE", "n"]
    return out


def validate_collar(df: pd.DataFrame, bhid: str, x: str, y: str, z: str) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Port of validCollar() returning:
      - summary (TYPE, n)
      - issues (rows with TYPE)
    """
    cols = [bhid, x, y, z]
    for c in cols:
        if c not in df.columns:
            raise ValueError(f"Column '{c}' not found in collar file.")

    collar = df[cols].copy()
    collar[bhid] = collar[bhid].astype(str)
    collar[[x, y, z]] = collar[[x, y, z]].apply(pd.to_numeric, errors="coerce")

    issues = []

    # 0 Zero/Null values
    cond = collar[(collar[x] == 0) | (collar[y] == 0) | (collar[z] == 0) | (collar.isnull().any(axis=1))]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "Zero/Null values"
        issues.append(tmp)

    # 1 Rounded coordinates
    cond = collar[(collar[x] % 1 == 0) & (collar[y] % 1 == 0) & (collar[z] % 1 == 0)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "Rounded coordinates"
        issues.append(tmp)

    # 2 duplicated Hole ID
    cond = collar[collar[bhid].duplicated(keep=False)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "duplicated Hole ID"
        issues.append(tmp)

    # 3 duplicated coordinates
    cond = collar[collar[[x, y, z]].duplicated(keep=False)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "duplicated coordinates"
        issues.append(tmp)

    # 4 inverted X and Y (heuristic from script)
    cond = collar[
        (collar[x] > (collar[y].mean() - collar[y].std()))
        & (collar[x] < (collar[y].mean() + collar[y].std()))
        & (collar[y] > (collar[x].mean() - collar[x].std()))
        & (collar[y] < (collar[x].mean() + collar[x].std()))
    ]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "inverted X and Y"
        issues.append(tmp)

    # 5 coordinates to be reviewed (5 sigma)
    c1 = (collar[x] > collar[x].mean() + 5 * collar[x].std()) | (collar[x] < collar[x].mean() - 5 * collar[x].std())
    c2 = (collar[y] > collar[y].mean() + 5 * collar[y].std()) | (collar[y] < collar[y].mean() - 5 * collar[y].std())
    c3 = (collar[z] > collar[z].mean() + 5 * collar[z].std()) | (collar[z] < collar[z].mean() - 5 * collar[z].std())
    cond = collar[c1 | c2 | c3]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "coordinates to be reviewed"
        issues.append(tmp)

    # 6 Holeid with spaces on last character
    cond = collar[collar[bhid].astype(str).str[-1:] == " "]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "Holeid with spaces on last character"
        issues.append(tmp)

    issues_df = pd.concat(issues, ignore_index=True) if issues else pd.DataFrame(columns=cols + ["TYPE"])
    summary = _summary_by_type(issues_df)
    return summary, issues_df


def validate_survey(
    df: pd.DataFrame,
    bhid: str,
    at: str,
    az: str,
    dip: str,
    dls_threshold: float = 15.0,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Port of validSurvey() returning:
      - summary (TYPE, n)
      - issues
      - dls_df (full DLS calc table)
    """
    for c in (bhid, at, az, dip):
        if c not in df.columns:
            raise ValueError(f"Column '{c}' not found in survey file.")

    survey = df[[bhid, at, az, dip]].copy()
    survey[bhid] = survey[bhid].astype(str)
    survey[[at, az, dip]] = survey[[at, az, dip]].apply(pd.to_numeric, errors="coerce")
    survey = survey.sort_values([bhid, at], ascending=True)

    issues = []

    # 0 invalid Dip/Azimuth
    cond = survey[(survey[dip] > 90) | (survey[dip] < -90) | (survey[az] > 360) | (survey[az] < -360)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "invalid Dip/Azimuth"
        issues.append(tmp)

    # 1 null values
    cond = survey[survey.isnull().any(axis=1)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "null values"
        issues.append(tmp)

    # 2 duplicated values (at, az, dip)
    cond = survey[survey[[at, az, dip]].duplicated(keep=False)]
    if len(cond):
        tmp = cond.copy()
        tmp["TYPE"] = "duplicated values"
        issues.append(tmp)

    # 3 DLS threshold
    dls_df = survey.copy()
    dls_df["dip2"] = dls_df.groupby([bhid])[dip].shift(-1)
    dls_df["az2"] = dls_df.groupby([bhid])[az].shift(-1)
    dls_df["at2"] = dls_df.groupby([bhid])[at].shift(1)
    dls_df["interval"] = dls_df[at] - dls_df["at2"]

    # Avoid division by 0
    dls_df["interval"] = dls_df["interval"].replace(0, np.nan)

    dls_df["DLS"] = (
        np.degrees(
            np.arccos(
                np.sin(np.radians(dls_df[dip])) * np.sin(np.radians(dls_df["dip2"]))
                + (np.cos(np.radians(dls_df[dip])) * np.cos(np.radians(dls_df["dip2"])) * np.cos(np.radians(dls_df["az2"] - dls_df[az])))
            )
        )
        / dls_df["interval"]
        * 30
    )

    cond = dls_df[dls_df["DLS"] > float(dls_threshold)].copy()
    if len(cond):
        tmp = cond[[bhid, at, az, dip]].copy()
        tmp["TYPE"] = f"DLS > {dls_threshold:g} degrees / 30 m"
        issues.append(tmp)

    issues_df = pd.concat(issues, ignore_index=True) if issues else pd.DataFrame(columns=[bhid, at, az, dip, "TYPE"])
    summary = _summary_by_type(issues_df)
    return summary, issues_df, dls_df


def validate_assay(
    df: pd.DataFrame,
    bhid: str,
    from_i: str,
    to_i: str,
    grade_fields: List[str],
    maxes: List[float],
    sampleid: Optional[str] = None,
) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Port of validAssay() returning:
      - summary (TYPE, n)
      - issues
    """
    cols = [bhid, from_i, to_i] + ([sampleid] if sampleid else []) + grade_fields
    for c in cols:
        if c not in df.columns:
            raise ValueError(f"Column '{c}' not found in assay file.")

    assay = df[cols].copy()
    assay[bhid] = assay[bhid].astype(str)
    assay[[from_i, to_i]] = assay[[from_i, to_i]].apply(pd.to_numeric, errors="coerce")
    assay[grade_fields] = assay[grade_fields].apply(pd.to_numeric, errors="coerce")
    assay = assay.sort_values([bhid, from_i, to_i])

    issues = []

    # 0 FROM/TO overlaps
    tmp = assay.copy()
    tmp["from_i2"] = tmp.groupby([bhid])[from_i].shift(-1)
    tmp["to_i2"] = tmp.groupby([bhid])[to_i].shift(1)
    cond = tmp[(tmp[to_i] > tmp["from_i2"]) | (tmp["to_i2"] > tmp[from_i])].copy()
    if len(cond):
        out = cond.drop(columns=["from_i2", "to_i2"])
        out["TYPE"] = "FROM/TO overlaps"
        issues.append(out)

    # 1 negative/zero values
    cond = assay[(assay[grade_fields] <= 0).any(axis=1)]
    if len(cond):
        out = cond.copy()
        out["TYPE"] = "negative/zero values"
        issues.append(out)

    # 2 unexpected grades ( > maxes)
    max_arr = np.array(maxes, dtype=float)
    cond = assay[(assay[grade_fields].values > max_arr).any(axis=1)]
    if len(cond):
        out = cond.copy()
        out["TYPE"] = "unexpected grades"
        issues.append(out)

    # 3 duplicated Sample ID
    if sampleid:
        cond = assay[assay[sampleid].duplicated(keep=False)]
        if len(cond):
            out = cond.copy()
            out["TYPE"] = "duplicated Sample ID"
            issues.append(out)

    # 4 recurring assays (script logic)
    tmp = assay.copy().fillna(0)
    tmp["SUM"] = tmp[grade_fields].sum(axis=1)
    cond = tmp[(tmp["SUM"].duplicated(keep=False)) & (tmp["SUM"] > 1)]
    cond = cond[cond[grade_fields].duplicated(keep=False)]
    if len(cond):
        out = cond.drop(columns=["SUM"]).copy()
        out["TYPE"] = "recurring assays"
        issues.append(out)

    issues_df = pd.concat(issues, ignore_index=True) if issues else pd.DataFrame(columns=cols + ["TYPE"])
    summary = _summary_by_type(issues_df)
    return summary, issues_df
