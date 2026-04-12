import csv, collections, sys

raw_path = sys.argv[1]
with open(raw_path) as f:
    reader = csv.DictReader(f)
    data = collections.defaultdict(list)
    for row in reader:
        data[row['exit_strategy']].append(float(row['return_pct']))

results = []
for strategy in sorted(data.keys()):
    returns = data[strategy]
    compound = 1.0
    for r in returns:
        compound *= (1 + r / 100)
    compound_pct = (compound - 1) * 100
    results.append((compound_pct, strategy, returns))

results.sort(key=lambda x: -x[0])
for i, (cpct, strat, rets) in enumerate(results, 1):
    yr_str = ", ".join(f"{r:.1f}" for r in rets)
    print(f"#{i} {strat}: compound={cpct:.1f}%  years=[{yr_str}]")
