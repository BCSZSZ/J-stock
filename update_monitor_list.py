"""
Append universe selection results to monitor_list.json
Avoids duplicates and preserves existing entries
"""
import json
from pathlib import Path
from datetime import datetime

def append_to_monitor_list(selection_json_path: str, monitor_list_path: str = 'data/monitor_list.json'):
    """
    Append top N stocks from universe selection to monitor list.
    
    Args:
        selection_json_path: Path to universe selection JSON
        monitor_list_path: Path to monitor_list.json (default: data/monitor_list.json)
    """
    # Load universe selection
    with open(selection_json_path, 'r', encoding='utf-8') as f:
        selection_data = json.load(f)
    
    # Load existing monitor list
    with open(monitor_list_path, 'r', encoding='utf-8') as f:
        monitor_data = json.load(f)
    
    # Get existing codes
    existing_codes = {ticker['code'] for ticker in monitor_data['tickers']}
    
    # Prepare new entries
    new_entries = []
    for ticker in selection_data['tickers']:
        code = ticker['code']
        if code not in existing_codes:
            new_entry = {
                'code': code,
                'name': ticker.get('name', f'Stock_{code}'),
                'sector': 'Unknown',  # Universe selector doesn't have sector info
                'added_date': datetime.now().strftime('%Y-%m-%d'),
                'reason': f"Universe selection (Rank #{ticker['rank']}, Score {ticker['total_score']:.3f})",
                'universe_rank': ticker['rank'],
                'universe_score': ticker['total_score']
            }
            new_entries.append(new_entry)
    
    # Append new entries
    monitor_data['tickers'].extend(new_entries)
    
    # Update metadata
    monitor_data['last_updated'] = datetime.now().strftime('%Y-%m-%d')
    monitor_data['version'] = '1.1'
    
    # Backup original
    backup_path = Path(monitor_list_path).parent / 'monitor_list_backup.json'
    with open(backup_path, 'w', encoding='utf-8') as f:
        json.dump(monitor_data, f, indent=2, ensure_ascii=False)
    
    # Save updated monitor list
    with open(monitor_list_path, 'w', encoding='utf-8') as f:
        json.dump(monitor_data, f, indent=2, ensure_ascii=False)
    
    print(f"✅ Monitor List更新完成")
    print(f"   原有股票: {len(existing_codes)}")
    print(f"   新增股票: {len(new_entries)}")
    print(f"   总计股票: {len(monitor_data['tickers'])}")
    print(f"\n   备份保存: {backup_path}")
    
    if len(new_entries) > 0:
        print(f"\n新增股票列表:")
        for entry in new_entries[:10]:  # Show first 10
            print(f"  - {entry['code']}: {entry['name']} (Rank #{entry['universe_rank']}, Score {entry['universe_score']:.3f})")
        if len(new_entries) > 10:
            print(f"  ... 还有 {len(new_entries) - 10} 支股票")
    
    return len(new_entries)


if __name__ == '__main__':
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python update_monitor_list.py <selection_json_path>")
        print("Example: python update_monitor_list.py data/universe/top50_selection_20260116_131231.json")
        sys.exit(1)
    
    selection_path = sys.argv[1]
    append_to_monitor_list(selection_path)
