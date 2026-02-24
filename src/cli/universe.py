import json
import os
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

import pandas as pd
from dotenv import load_dotenv

from src.data.stock_data_manager import StockDataManager
from src.data.pipeline import StockETLPipeline
from src.universe.stock_selector import UniverseSelector


def _get_api_key() -> Optional[str]:
    load_dotenv()
    return os.getenv("JQUANTS_API_KEY")


def _load_codes_from_csv(csv_path: Path, limit: Optional[int]) -> List[str]:
    if not csv_path.exists():
        raise FileNotFoundError(f"未找到CSV文件: {csv_path}")

    df = pd.read_csv(csv_path, encoding="utf-8")
    if "Code" not in df.columns:
        raise ValueError("CSV缺少Code列")

    codes = df["Code"].astype(str).str.strip().tolist()
    if limit:
        codes = codes[:limit]

    return codes


def _load_checkpoint(path: Path) -> dict:
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_checkpoint(path: Path, state: dict) -> None:
    state["updated_at"] = datetime.now().isoformat()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def _run_universe_scoring(
    *,
    api_key: str,
    csv_path: Path,
    top_n: int,
    limit: Optional[int],
    batch_size: int,
    resume: bool,
    checkpoint: Optional[str],
    no_fetch: bool,
    workers: int,
    score_model: str,
    output_dir: Path,
    output_subdir: str,
) -> Tuple[pd.DataFrame, Path, Path]:
    """Run the reusable scoring pipeline and return globally scored data."""
    codes = _load_codes_from_csv(csv_path, limit)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

    scoring_dir = output_dir / output_subdir
    scoring_dir.mkdir(parents=True, exist_ok=True)

    checkpoints_dir = output_dir / "checkpoints"
    checkpoints_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = (
        Path(checkpoint)
        if checkpoint
        else checkpoints_dir / f"universe_run_{run_id}.json"
    )

    processed_codes = set()
    failed_codes = set()
    last_index = 0
    consolidated_scores_path = scoring_dir / f"scores_all_{score_model}_{run_id}.parquet"

    if resume:
        state = _load_checkpoint(checkpoint_path)
        if state:
            print(f"🔁 断点续传: {checkpoint_path}")
            run_id = state.get("run_id", run_id)
            processed_codes = set(state.get("processed_codes", []))
            failed_codes = set(state.get("failed_codes", []))
            last_index = int(state.get("last_index", 0))
            consolidated_scores_path = Path(
                state.get("scores_path", consolidated_scores_path)
            )
        else:
            print("⚠️ 未找到有效checkpoint，按新任务启动")

    _save_checkpoint(
        checkpoint_path,
        {
            "run_id": run_id,
            "csv_file": str(csv_path),
            "top_n": top_n,
            "batch_size": batch_size,
            "score_model": score_model,
            "processed_codes": list(processed_codes),
            "failed_codes": list(failed_codes),
            "last_index": last_index,
            "scores_path": str(consolidated_scores_path),
            "created_at": datetime.now().isoformat(),
        },
    )

    manager = StockDataManager(api_key=api_key)
    selector = UniverseSelector(
        manager,
        workers=workers,
        score_model=score_model,
        output_dir=str(output_dir),
    )

    print(
        f"🚀 开始打分 (Top {top_n})，股票数: {len(codes)}，批大小: {batch_size}，"
        f"score_model={score_model}, workers={workers}"
    )

    total = len(codes)
    start_idx = last_index

    min_history_rows = 300
    initial_lookback_days = 450

    while start_idx < total:
        end_idx = min(start_idx + batch_size, total)
        batch_codes = codes[start_idx:end_idx]
        batch_codes = [c for c in batch_codes if c not in processed_codes]

        if not batch_codes:
            start_idx = end_idx
            continue

        print(f"\n[Batch {start_idx}-{end_idx}] 处理 {len(batch_codes)} 支股票")

        # Explicit data preparation stage:
        # if no_fetch is False, run ETL first, then score with no_fetch=True.
        # This avoids duplicate fetch calls and makes pipeline behavior transparent.
        if not no_fetch:
            try:
                pipeline = StockETLPipeline(api_key, data_root="./data")
                prep_summary = pipeline.run_batch(
                    batch_codes,
                    fetch_aux_data=False,
                    recompute_features=False,
                    min_history_rows=min_history_rows,
                    initial_lookback_days=initial_lookback_days,
                )
                if prep_summary.get("failed", 0) > 0:
                    print(
                        f"⚠️ 批次预处理失败 {prep_summary['failed']}/{prep_summary['total']}，将继续对成功样本打分"
                    )
            except Exception as e:
                print(f"❌ 批次预处理失败: {e}")
                failed_codes.update(batch_codes)
                _save_checkpoint(
                    checkpoint_path,
                    {
                        "run_id": run_id,
                        "csv_file": str(csv_path),
                        "top_n": top_n,
                        "batch_size": batch_size,
                        "score_model": score_model,
                        "processed_codes": list(processed_codes),
                        "failed_codes": list(failed_codes),
                        "last_index": end_idx,
                        "scores_path": str(consolidated_scores_path),
                        "created_at": datetime.now().isoformat(),
                    },
                )
                start_idx = end_idx
                continue

        try:
            result = selector.run_selection(
                top_n=top_n,
                test_mode=False,
                test_limit=10,
                ticker_list=batch_codes,
                apply_filters=False,
                return_full=True,
                no_fetch=True,
            )
            if not isinstance(result, tuple) or len(result) != 2:
                raise RuntimeError("run_selection did not return expected (df_top, df_scored)")
            _, df_scored = result
            if not isinstance(df_scored, pd.DataFrame):
                raise RuntimeError("run_selection returned invalid df_scored")

            if df_scored.empty:
                print("⚠️ 本批次无可评分样本（常见原因: 历史数据不足/新股）")
        except Exception as e:
            print(f"❌ 批次失败: {e}")
            failed_codes.update(batch_codes)
            _save_checkpoint(
                checkpoint_path,
                {
                    "run_id": run_id,
                    "csv_file": str(csv_path),
                    "top_n": top_n,
                    "batch_size": batch_size,
                    "score_model": score_model,
                    "processed_codes": list(processed_codes),
                    "failed_codes": list(failed_codes),
                    "last_index": end_idx,
                    "scores_path": str(consolidated_scores_path),
                    "created_at": datetime.now().isoformat(),
                },
            )
            start_idx = end_idx
            continue

        if not df_scored.empty:
            try:
                if consolidated_scores_path.exists():
                    existing = pd.read_parquet(consolidated_scores_path)
                    combined = pd.concat([existing, df_scored], ignore_index=True)
                    subset_cols = [
                        c for c in ["Code", "DataDate"] if c in combined.columns
                    ]
                    if subset_cols:
                        combined = combined.drop_duplicates(
                            subset=subset_cols, keep="last"
                        )
                    combined.to_parquet(consolidated_scores_path, index=False)
                else:
                    df_scored.to_parquet(consolidated_scores_path, index=False)
            except Exception as e:
                print(f"⚠️ 无法追加合并分数: {e}")

        processed_codes.update(batch_codes)

        _save_checkpoint(
            checkpoint_path,
            {
                "run_id": run_id,
                "csv_file": str(csv_path),
                "top_n": top_n,
                "batch_size": batch_size,
                "score_model": score_model,
                "processed_codes": list(processed_codes),
                "failed_codes": list(failed_codes),
                "last_index": end_idx,
                "scores_path": str(consolidated_scores_path),
                "created_at": datetime.now().isoformat(),
            },
        )

        start_idx = end_idx

    if not consolidated_scores_path.exists():
        raise RuntimeError(
            "未生成合并分数文件（可能全部样本历史数据不足）。"
            "可尝试去掉 --limit、确认数据范围，或放宽筛选策略。"
        )

    all_scores = pd.read_parquet(consolidated_scores_path)
    all_scores = selector.normalize_features(all_scores)
    all_scores = selector.calculate_scores(all_scores)

    final_scores_path = scoring_dir / f"scores_all_final_{score_model}_{run_id}.parquet"
    all_scores.to_parquet(final_scores_path, index=False)

    if no_fetch and len(processed_codes) < len(codes):
        print(
            "⚠️ NO-FETCH模式下部分股票缺少本地features，已被跳过。"
            f"成功处理: {len(processed_codes)}/{len(codes)}"
        )

    return all_scores, consolidated_scores_path, final_scores_path


def _sector_quota(sector_count: int, min_per_sector: int, max_per_sector: int) -> int:
    if sector_count <= 25:
        return min_per_sector
    if sector_count <= 60:
        return min(min_per_sector + 1, max_per_sector)
    if sector_count <= 120:
        return min(min_per_sector + 2, max_per_sector)
    return max_per_sector


def _pick_with_size_balance(df_sector: pd.DataFrame, quota: int, size_col: str) -> pd.DataFrame:
    buckets = []
    for size, g in df_sector.groupby(size_col, dropna=False):
        bucket = g.sort_values("TotalScore", ascending=False).copy()
        if not bucket.empty:
            buckets.append(bucket)

    if not buckets:
        return df_sector.head(quota)

    indices = [0] * len(buckets)
    picks = []

    while len(picks) < quota:
        progressed = False
        for i, bucket in enumerate(buckets):
            if len(picks) >= quota:
                break
            if indices[i] < len(bucket):
                picks.append(bucket.iloc[indices[i]])
                indices[i] += 1
                progressed = True
        if not progressed:
            break

    if not picks:
        return df_sector.head(quota)

    picked = pd.DataFrame(picks)
    picked = picked.drop_duplicates(subset=["Code"], keep="first")
    return picked.head(quota)


def cmd_universe(args):
    """股票宇宙选股（全市场评分 + TopN）"""
    api_key = _get_api_key()
    if not api_key:
        print("❌ 错误: 未找到 JQUANTS_API_KEY")
        return

    output_dir = Path(args.output_dir or "data/universe")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = Path(args.csv_file) if args.csv_file else Path("data/jpx_final_list.csv")

    print("\n" + "=" * 80)
    print("J-Stock Universe Selector - CLI")
    if args.no_fetch:
        print("⚡ NO-FETCH模式: 跳过数据抓取，使用现有本地features")
    else:
        print("📥 默认预处理: 先抓取并补齐最近300行历史，再计算features")
    print("=" * 80 + "\n")

    try:
        all_scores, raw_scores_path, final_scores_path = _run_universe_scoring(
            api_key=api_key,
            csv_path=csv_path,
            top_n=args.top_n,
            limit=args.limit,
            batch_size=args.batch_size or 100,
            resume=args.resume,
            checkpoint=args.checkpoint,
            no_fetch=args.no_fetch,
            workers=args.workers,
            score_model=args.score_model,
            output_dir=output_dir,
            output_subdir="scoring",
        )
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        return

    manager = StockDataManager(api_key=api_key)
    selector = UniverseSelector(
        manager,
        workers=args.workers,
        score_model=args.score_model,
        output_dir=str(output_dir),
    )

    df_top_final = all_scores.nlargest(args.top_n, "TotalScore").copy()
    df_top_final["Rank"] = range(1, len(df_top_final) + 1)

    selector.print_summary(df_top_final, n=min(10, len(df_top_final)))
    json_path_out, csv_path_out = selector.save_selection_results(df_top_final, format="both")
    txt_path_out = selector.save_scores_txt(all_scores, df_top_final, top_n=args.top_n)

    print("\n✅ 全量选股完成")
    print(f"📦 原始分数: {raw_scores_path}")
    print(f"📦 全局分数: {final_scores_path}")
    if json_path_out:
        print(f"📄 JSON: {json_path_out}")
    if csv_path_out:
        print(f"📊 CSV:  {csv_path_out}")
    if txt_path_out:
        print(f"🧾 TXT:  {txt_path_out}")


def cmd_universe_sector(args):
    """按33板块配额构建代表池（12-15支/板块）"""
    api_key = _get_api_key()
    if not api_key:
        print("❌ 错误: 未找到 JQUANTS_API_KEY")
        return

    output_dir = Path(args.output_dir or "data/universe")
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = Path(args.csv_file) if args.csv_file else Path("data/jpx_final_list.csv")

    print("\n" + "=" * 80)
    print("J-Stock Universe Sector Pool Builder")
    if args.no_fetch:
        print("⚡ NO-FETCH模式: 跳过数据抓取，使用现有本地features")
    else:
        print("📥 默认预处理: 先抓取并补齐最近300行历史，再计算features")
    print("=" * 80 + "\n")

    try:
        all_scores, _, final_scores_path = _run_universe_scoring(
            api_key=api_key,
            csv_path=csv_path,
            top_n=max(args.max_per_sector * 33 * args.candidate_multiplier, 500),
            limit=args.limit,
            batch_size=args.batch_size or 100,
            resume=args.resume,
            checkpoint=args.checkpoint,
            no_fetch=args.no_fetch,
            workers=args.workers,
            score_model=args.score_model,
            output_dir=output_dir,
            output_subdir="scoring",
        )
    except Exception as e:
        print(f"❌ 运行失败: {e}")
        return

    meta = pd.read_csv(csv_path, encoding="utf-8")
    meta["Code"] = meta["Code"].astype(str).str.strip().str.zfill(4)
    all_scores["Code"] = all_scores["Code"].astype(str).str.strip().str.zfill(4)

    merged = all_scores.merge(meta, on="Code", how="left")

    # Keep only common stocks with valid sector labels.
    merged = merged[merged.get("Type", "Stock") == "Stock"].copy()
    sector_col = args.sector_col
    size_col = args.size_col
    merged = merged[merged[sector_col].notna()].copy()
    merged = merged[~merged[sector_col].isin(["-", "", "Unknown"])].copy()

    if merged.empty:
        print("❌ 没有可用样本（请检查CSV字段和本地features）")
        return

    sector_pool_rows = []
    summary_rows = []

    for sector, g in merged.groupby(sector_col):
        g_sorted = g.sort_values("TotalScore", ascending=False).copy()
        quota = _sector_quota(len(g_sorted), args.min_per_sector, args.max_per_sector)

        candidate_cap = min(len(g_sorted), quota * args.candidate_multiplier)
        candidates = g_sorted.head(candidate_cap)

        if args.size_balance:
            picked = _pick_with_size_balance(candidates, quota, size_col=size_col)
        else:
            picked = candidates.head(quota)

        picked = picked.copy()
        picked["sector_quota"] = quota
        picked["sector_name"] = sector

        summary_rows.append(
            {
                "sector_name": sector,
                "available": len(g_sorted),
                "candidate_cap": candidate_cap,
                "quota": quota,
                "selected": len(picked),
                "avg_score": picked["TotalScore"].mean() if not picked.empty else None,
            }
        )

        sector_pool_rows.append(picked)

    if not sector_pool_rows:
        print("❌ 未生成任何板块代表股")
        return

    pool = pd.concat(sector_pool_rows, ignore_index=True)
    pool = pool.sort_values(["sector_name", "TotalScore"], ascending=[True, False])

    pool["pool_rank"] = (
        pool.groupby("sector_name")["TotalScore"].rank(ascending=False, method="first").astype(int)
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    sector_dir = output_dir / "sector_pool"
    sector_dir.mkdir(parents=True, exist_ok=True)

    pool_path = sector_dir / f"sector_pool_33x{args.min_per_sector}to{args.max_per_sector}_{args.score_model}_{timestamp}.csv"
    summary_path = sector_dir / f"sector_pool_summary_{args.score_model}_{timestamp}.csv"
    pool.to_csv(pool_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(summary_rows).sort_values("sector_name").to_csv(
        summary_path, index=False, encoding="utf-8-sig"
    )

    print("✅ 板块代表池生成完成")
    print(f"📦 全局分数: {final_scores_path}")
    print(f"📊 代表池: {pool_path}")
    print(f"📑 汇总:   {summary_path}")
    print(f"📈 板块数: {pool['sector_name'].nunique()}, 股票数: {len(pool)}")

    if args.write_monitor_list:
        monitor_payload = {
            "version": "2.0",
            "selection_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "description": "Sector representative pool generated by universe-sector",
            "score_model": args.score_model,
            "tickers": [
                {
                    "code": row["Code"],
                    "name": row.get("銘柄名", row.get("CompanyName", f"Stock_{row['Code']}")),
                    "sector": row["sector_name"],
                    "size": row.get(size_col, "Unknown"),
                    "score": float(row["TotalScore"]),
                }
                for _, row in pool.iterrows()
            ],
        }

        monitor_out = sector_dir / f"sector_pool_monitor_{args.score_model}_{timestamp}.json"
        with open(monitor_out, "w", encoding="utf-8") as f:
            json.dump(monitor_payload, f, indent=2, ensure_ascii=False)
        print(f"📄 Monitor JSON: {monitor_out}")
