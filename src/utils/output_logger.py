"""
输出日志工具
将命令行输出同步保存到文件
"""
import sys
from pathlib import Path
from datetime import datetime
from typing import Optional


class OutputLogger:
    """
    双向输出器：同时输出到控制台和文件
    """
    
    def __init__(self, output_dir: str = './output', prefix: str = 'output'):
        """
        Args:
            output_dir: 输出目录
            prefix: 文件名前缀
        """
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名：prefix_YYYYMMDD_HHMMSS.txt
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.log_file = self.output_dir / f"{prefix}_{timestamp}.txt"
        
        # 保存原始stdout
        self.original_stdout = sys.stdout
        self.original_stderr = sys.stderr
        
        # 打开日志文件
        self.file_handle = open(self.log_file, 'w', encoding='utf-8')
        
    def write(self, text: str):
        """写入文本到控制台和文件"""
        self.original_stdout.write(text)
        self.file_handle.write(text)
        self.file_handle.flush()  # 立即刷新到文件
        
    def flush(self):
        """刷新缓冲"""
        self.original_stdout.flush()
        self.file_handle.flush()
        
    def close(self):
        """关闭日志文件"""
        if self.file_handle:
            self.file_handle.close()
            print(f"\n📄 输出已保存到: {self.log_file}", file=self.original_stdout)
    
    def __enter__(self):
        """上下文管理器入口"""
        sys.stdout = self
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        sys.stdout = self.original_stdout
        self.close()
        return False


def create_logger(command: str, **kwargs) -> OutputLogger:
    """
    创建输出日志器
    
    Args:
        command: 命令名称（backtest, portfolio, signal等）
        **kwargs: 其他参数（如ticker等）
        
    Returns:
        OutputLogger实例
    """
    # 根据命令类型和参数生成前缀
    if command == 'backtest':
        ticker = kwargs.get('ticker', 'unknown')
        prefix = f"backtest_{ticker}"
    elif command == 'portfolio':
        prefix = "portfolio"
    elif command == 'signal':
        ticker = kwargs.get('ticker', 'unknown')
        date = kwargs.get('date', 'unknown')
        prefix = f"signal_{ticker}_{date}"
    else:
        prefix = command
    
    return OutputLogger(prefix=prefix)
