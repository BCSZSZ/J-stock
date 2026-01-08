"""
Test script to verify J-Stock-Analyzer setup.
Run this after installing dependencies to ensure everything works.
"""
import sys
from pathlib import Path

def test_imports():
    """Test that all required packages are installed."""
    print("Testing imports...")
    try:
        import pandas as pd
        print("✅ pandas")
        
        import ta
        print("✅ ta (technical analysis library)")
        
        import requests
        print("✅ requests")
        
        from dotenv import load_dotenv
        print("✅ python-dotenv")
        
        import fastparquet
        print("✅ fastparquet")
        
        import pyarrow
        print("✅ pyarrow")
        
        from tqdm import tqdm
        print("✅ tqdm (progress bars)")
        
        return True
    except ImportError as e:
        print(f"❌ Import failed: {e}")
        return False

def test_env_file():
    """Test that .env file exists and has API key."""
    print("\nTesting environment configuration...")
    env_path = Path('.env')
    
    if not env_path.exists():
        print("❌ .env file not found!")
        print("   Create it from .env.example: cp .env.example .env")
        return False
    
    print("✅ .env file exists")
    
    from dotenv import load_dotenv
    import os
    
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY')
    
    if not api_key or api_key == 'your_api_key_here':
        print("❌ JQUANTS_API_KEY not configured!")
        print("   Edit .env and add your actual API key")
        return False
    
    print("✅ JQUANTS_API_KEY configured")
    return True

def test_project_structure():
    """Test that project structure is correct."""
    print("\nTesting project structure...")
    
    required_files = [
        'src/client/jquants_client.py',
        'src/data/stock_data_manager.py',
        'src/data/pipeline.py',
        'src/main.py',
        'requirements.txt',
    ]
    
    all_exist = True
    for file_path in required_files:
        path = Path(file_path)
        if path.exists():
            print(f"✅ {file_path}")
        else:
            print(f"❌ {file_path} not found!")
            all_exist = False
    
    return all_exist

def test_data_lake_structure():
    """Test that data lake directories can be created."""
    print("\nTesting data lake structure...")
    
    from src.data.stock_data_manager import StockDataManager
    import os
    from dotenv import load_dotenv
    
    load_dotenv()
    api_key = os.getenv('JQUANTS_API_KEY', 'dummy_key_for_test')
    
    try:
        manager = StockDataManager(api_key=api_key)
        
        # Check all directories were created
        for name, path in manager.dirs.items():
            if path.exists() and path.is_dir():
                print(f"✅ {name:20s} {path}")
            else:
                print(f"❌ {name:20s} failed to create")
                return False
        
        return True
    except Exception as e:
        print(f"❌ Data lake initialization failed: {e}")
        return False

def test_technical_indicators():
    """Test that ta library works correctly."""
    print("\nTesting technical indicators (ta library)...")
    
    try:
        import pandas as pd
        from ta.trend import EMAIndicator
        from ta.momentum import RSIIndicator
        
        # Create dummy data
        data = pd.DataFrame({
            'Close': [100 + i for i in range(100)]
        })
        
        # Test EMA
        ema = EMAIndicator(close=data['Close'], window=20)
        data['EMA_20'] = ema.ema_indicator()
        print("✅ EMA indicator works")
        
        # Test RSI
        rsi = RSIIndicator(close=data['Close'], window=14)
        data['RSI'] = rsi.rsi()
        print("✅ RSI indicator works")
        
        return True
    except Exception as e:
        print(f"❌ Indicator test failed: {e}")
        return False

def test_python_version():
    """Test Python version compatibility."""
    print("\nTesting Python version...")
    
    version = sys.version_info
    version_str = f"{version.major}.{version.minor}.{version.micro}"
    print(f"Python version: {version_str}")
    
    if version.major == 3 and version.minor >= 10:
        print("✅ Python version compatible (3.10+)")
        return True
    else:
        print("⚠️  Python 3.10+ recommended")
        return False

def main():
    """Run all tests."""
    print("="*60)
    print("J-Stock-Analyzer Setup Verification (Python 3.14 Compatible)")
    print("="*60)
    
    tests = [
        ("Python version", test_python_version),
        ("Package imports", test_imports),
        ("Environment config", test_env_file),
        ("Project structure", test_project_structure),
        ("Data Lake structure", test_data_lake_structure),
        ("Technical indicators", test_technical_indicators),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append(result)
        except Exception as e:
            print(f"❌ {name} failed with error: {e}")
            results.append(False)
    
    print("\n" + "="*60)
    if all(results):
        print("✅ ALL TESTS PASSED!")
        print("="*60)
        print("\nYou're ready to run:")
        print("  python src/main.py         # Run batch ETL")
        print("  python examples.py         # See usage examples")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("="*60)
        print("\nPlease fix the issues above before running main.py")
        return 1

if __name__ == "__main__":
    sys.exit(main())
