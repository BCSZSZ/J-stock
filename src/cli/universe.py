def cmd_universe(args):
    """股票宇宙选股（正式版命令，支持分批与断点续传）"""
    import os
    import json
    from dotenv import load_dotenv
    from src.data.stock_data_manager import StockDataManager
    from src.universe.stock_selector import UniverseSelector
    import pandas as pd
    from pathlib import Path
    from datetime import datetime

    load_dotenv()
    api_key = os.getenv("JQUANTS_API_KEY")
    if not api_key:
        print("❌ 错误: 未找到 JQUANTS_API_KEY")
        return

    print("\n" + "=" * 80)
    print("J-Stock Universe Selector - CLI (Batch + Resume)")
    if args.no_fetch:
        print("⚡ NO-FETCH模式: 跳过数据抓取，使用现有本地数据")
    print("=" * 80 + "\n")
    manager = StockDataManager(api_key=api_key)
    selector = UniverseSelector(manager)

    csv_path = Path(args.csv_file) if args.csv_file else Path("data/jpx_final_list.csv")
    if not csv_path.exists():
        print(f"❌ 错误: 未找到CSV文件 {csv_path}")
        return
    df = pd.read_csv(csv_path, encoding="utf-8")
    if "Code" not in df.columns:
        print("❌ 错误: CSV缺少Code列")
        return
    full_codes = df["Code"].astype(str).str.strip().tolist()
    if args.limit:
        full_codes = full_codes[: args.limit]
        print(f"🧪 限制模式: 仅处理前 {args.limit} 支股票")

    checkpoints_dir = Path("data/universe/checkpoints")
    checkpoints_dir.mkdir(parents=True, exist_ok=True)

    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    checkpoint_path = Path(args.checkpoint) if args.checkpoint else checkpoints_dir / f"universe_run_{run_id}.json"

    def load_checkpoint(path: Path) -> dict:
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def save_checkpoint(state: dict) -> None:
        state["updated_at"] = datetime.now().isoformat()
        with open(checkpoint_path, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)

    processed_codes = set()
    failed_codes = set()
    last_index = 0
    batch_size = args.batch_size or 100

    consolidated_scores_path = Path("data/universe") / f"scores_all_{run_id}.parquet"

    if args.resume:
        state = load_checkpoint(checkpoint_path)
        if state:
            print(f"🔁 断点续传: {checkpoint_path}")
            run_id = state.get("run_id", run_id)
            processed_codes = set(state.get("processed_codes", []))
            failed_codes = set(state.get("failed_codes", []))
            last_index = int(state.get("last_index", 0))
            consolidated_scores_path = Path(state.get("scores_path", consolidated_scores_path))
        else:
            print("⚠️ 未找到有效的checkpoint，按新任务启动")

    save_checkpoint(
        {
            "run_id": run_id,
            "csv_file": str(csv_path),
            "top_n": args.top_n,
            "batch_size": batch_size,
            "processed_codes": list(processed_codes),
            "failed_codes": list(failed_codes),
            "last_index": last_index,
            "scores_path": str(consolidated_scores_path),
            "created_at": datetime.now().isoformat(),
        }
    )

    print(f"🚀 开始选股 (Top {args.top_n})，股票数: {len(full_codes)}，批大小: {batch_size}")

    total = len(full_codes)
    start_idx = last_index
    while start_idx < total:
        end_idx = min(start_idx + batch_size, total)
        batch_codes = full_codes[start_idx:end_idx]

        batch_codes = [c for c in batch_codes if c not in processed_codes]
        if not batch_codes:
            start_idx = end_idx
            continue

        print(f"\n[Batch {start_idx}-{end_idx}] 处理 {len(batch_codes)} 支股票")
        try:
            df_top, df_scored = selector.run_selection(
                top_n=args.top_n,
                test_mode=False,
                test_limit=10,
                ticker_list=batch_codes,
                apply_filters=False,
                return_full=True,
                no_fetch=args.no_fetch,
            )
        except Exception as e:
            print(f"❌ 批次失败: {e}")
            for c in batch_codes:
                failed_codes.add(c)
            save_checkpoint(
                {
                    "run_id": run_id,
                    "csv_file": str(csv_path),
                    "top_n": args.top_n,
                    "batch_size": batch_size,
                    "processed_codes": list(processed_codes),
                    "failed_codes": list(failed_codes),
                    "last_index": end_idx,
                    "scores_path": str(consolidated_scores_path),
                    "created_at": datetime.now().isoformat(),
                }
            )
            start_idx = end_idx
            continue

        try:
            if consolidated_scores_path.exists():
                existing = pd.read_parquet(consolidated_scores_path)
                combined = pd.concat([existing, df_scored], ignore_index=True)
                subset_cols = [c for c in ["Code", "DataDate"] if c in combined.columns]
                if subset_cols:
                    combined = combined.drop_duplicates(subset=subset_cols, keep="last")
                combined.to_parquet(consolidated_scores_path, index=False)
            else:
                df_scored.to_parquet(consolidated_scores_path, index=False)
        except Exception as e:
            print(f"⚠️ 无法追加合并分数: {e}")

        for c in batch_codes:
            processed_codes.add(c)

        save_checkpoint(
            {
                "run_id": run_id,
                "csv_file": str(csv_path),
                "top_n": args.top_n,
                "batch_size": batch_size,
                "processed_codes": list(processed_codes),
                "failed_codes": list(failed_codes),
                "last_index": end_idx,
                "scores_path": str(consolidated_scores_path),
                "created_at": datetime.now().isoformat(),
            }
        )

        start_idx = end_idx

    if consolidated_scores_path.exists():
        all_scores = pd.read_parquet(consolidated_scores_path)

        print(f"\n📊 全局归一化 ({len(all_scores)} 支股票)")

        all_scores = selector.normalize_features(all_scores)
        all_scores = selector.calculate_scores(all_scores)

        print(
            f"   权重分配: Vol={selector.WEIGHT_VOLATILITY}, Liq={selector.WEIGHT_LIQUIDITY}, "
            f"Trend={selector.WEIGHT_TREND}, Momentum={selector.WEIGHT_MOMENTUM}, "
            f"VolSurge={selector.WEIGHT_VOLUME_SURGE}"
        )
        print(f"   分数范围: {all_scores['TotalScore'].min():.3f} - {all_scores['TotalScore'].max():.3f}")

        df_top_final = all_scores.nlargest(args.top_n, "TotalScore").copy()
        df_top_final["Rank"] = range(1, len(df_top_final) + 1)

        selector.print_summary(df_top_final, n=min(10, len(df_top_final)))

        json_path_out, csv_path_out = selector.save_selection_results(df_top_final, format="both")
        txt_path_out = selector.save_scores_txt(all_scores, df_top_final, top_n=args.top_n)

        print(f"\n✅ 全量选股完成")
        if json_path_out:
            print(f"📄 JSON: {json_path_out}")
        if csv_path_out:
            print(f"📊 CSV:  {csv_path_out}")
        if txt_path_out:
            print(f"🧾 TXT:  {txt_path_out}")

    else:
        print("⚠️ 未生成合并分数文件，无法输出最终结果")
