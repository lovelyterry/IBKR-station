#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
IBKR & Generic CSV Importer to Pandas In-Memory Database
这是一个将指定目录下的 CSV 文件导入 Pandas 内存数据库（DataFrame 字典）的工具脚本。
支持普通的 CSV 文件和 IBKR（盈透证券）多段式（Header/Data）CSV 导出文件。
并提供交互式查询终端和 Python Shell 以便实时分析。
"""

import os
import sys
import csv
import argparse
import cmd
import code
from pathlib import Path

# 尝试导入 pandas
try:
    import pandas as pd
except ImportError:
    print("错误: 运行此脚本需要 'pandas' 库。")
    print("请使用以下命令安装: pip install pandas")
    sys.exit(1)

def is_multi_section_csv(filepath):
    """
    检测是否为 IBKR 多段式 CSV。
    特征：前几行非空行的第二个字段为 'Header' 或 'Data'。
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            reader = csv.reader(f)
            count = 0
            for row in reader:
                if not row:
                    continue
                if len(row) < 2:
                    return False
                if row[1] not in ('Header', 'Data'):
                    return False
                count += 1
                if count >= 5:
                    break
            return count > 0
    except Exception:
        return False

def load_ibkr_csv(filepath):
    """
    解析 IBKR 多段式 CSV，将不同 Section 拆分为独立的 DataFrame 字典。
    """
    sections = {}
    with open(filepath, 'r', encoding='utf-8') as f:
        reader = csv.reader(f)
        for row in reader:
            if not row:
                continue
            sec_name = row[0]
            row_type = row[1]
            content = row[2:]
            
            if row_type == 'Header':
                if sec_name not in sections:
                    sections[sec_name] = {
                        'headers': content,
                        'data': []
                    }
            elif row_type == 'Data':
                if sec_name in sections:
                    sections[sec_name]['data'].append(content)
                    
    dfs = {}
    for sec_name, sec_data in sections.items():
        headers = sec_data['headers']
        data = sec_data['data']
        
        # 确保数据列数和 header 一致
        clean_data = []
        for row in data:
            if len(row) < len(headers):
                row = row + [None] * (len(headers) - len(row))
            elif len(row) > len(headers):
                row = row[:len(headers)]
            clean_data.append(row)

        # IBKR 导出的 CSV 数据行通常是逆序（最新在前），在此将其反转为正序（最旧在前）
        clean_data.reverse()

        df = pd.DataFrame(clean_data, columns=headers)
        df['source_file'] = os.path.basename(filepath)
        dfs[sec_name] = df
        
    return dfs

def load_standard_csv(filepath):
    """
    加载普通的标准 CSV 文件。
    """
    df = pd.read_csv(filepath)
    df['source_file'] = os.path.basename(filepath)
    table_name = Path(filepath).stem
    return {table_name: df}

def auto_convert_types(df):
    """
    自动转换 DataFrame 列的类型（如数值、日期），以便于计算和筛选。
    """
    for col in df.columns:
        if col == 'source_file':
            continue
        
        s = df[col].copy()
        # 替换 IBKR 中常见的空值占位符 '-' 或空字符串
        s = s.replace({'-': None, '': None, 'nan': None, 'NAN': None})
        
        # 尝试转换为数值型
        try:
            non_null = s.dropna()
            if not non_null.empty:
                # 检查是否全部可转换为 float/int
                pd.to_numeric(non_null, errors='raise')
                df[col] = pd.to_numeric(s, errors='coerce')
                continue
        except (ValueError, TypeError):
            pass
            
        # 尝试转换为日期型
        if '日期' in col or 'date' in col.lower() or 'time' in col.lower():
            try:
                # 尝试解析，如果不报错就转换整个列
                pd.to_datetime(s.dropna(), errors='raise')
                df[col] = pd.to_datetime(s, errors='coerce')
                continue
            except (ValueError, TypeError):
                pass
                
    return df

def print_dataframe_ascii(df, max_rows=15, max_col_width=25):
    """
    在终端中以漂亮的 ASCII 表格形式打印 DataFrame，并妥善处理中文字符对齐和列宽。
    """
    if df.empty:
        print("数据为空。")
        return

    import numpy as np
    display_df = df.head(max_rows)
    headers = [str(col) for col in df.columns]

    # 辅助函数：计算包含中文的字符串的实际终端显示宽度（GBK 编码下中文占2字节，英文占1字节）
    def display_len(s):
        try:
            return len(str(s).encode('gbk', errors='ignore'))
        except Exception:
            return len(str(s))

    # 辅助函数：对齐含中文的字符串
    def pad_string(s, width):
        s_str = str(s) if s is not None and not pd.isna(s) else ""
        if len(s_str) > max_col_width:
            s_str = s_str[:max_col_width-3] + "..."
        curr_len = display_len(s_str)
        padding = max(0, width - curr_len)
        return s_str + " " * padding

    # 计算表头的显示长度作为列宽的基准值
    col_widths = [display_len(h) for h in headers]

    # 收集每一行的数据并更新列宽
    rows = []
    for _, row in display_df.iterrows():
        row_strs = []
        for i, val in enumerate(row):
            col_name = df.columns[i]
            if isinstance(val, (float, np.floating)):
                if col_name in {'数量', '价格', '佣金', 'Quantity', 'Price', 'Commission'}:
                    val_str = f"{val:.4f}"
                elif col_name in {'总额', '净额', '持仓成本', '已实现盈亏', '期权权利金', '已实现盈亏(含期权)', 'Amount', 'Net', 'Total Cost', 'Realized P&L'}:
                    val_str = f"{val:.2f}"
                else:
                    val_str = f"{val:.4f}"
            else:
                val_str = str(val) if val is not None and not pd.isna(val) else ""

            if len(val_str) > max_col_width:
                val_str = val_str[:max_col_width-3] + "..."
            row_strs.append(val_str)
            col_widths[i] = max(col_widths[i], display_len(val_str))
        rows.append(row_strs)
        
    # 生成横向分隔线
    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    print(sep)
    
    # 打印表头
    header_row = "| " + " | ".join(pad_string(h, col_widths[i]) for i, h in enumerate(headers)) + " |"
    print(header_row)
    print(sep.replace('-', '='))
    
    # 打印数据行
    for row in rows:
        data_row = "| " + " | ".join(pad_string(val, col_widths[i]) for i, val in enumerate(row)) + " |"
        print(data_row)
        
    print(sep)
    if len(df) > max_rows:
        print(f"提示: 已自动限制显示前 {max_rows} 行，总共有 {len(df)} 行数据。")

class PandasShell(cmd.Cmd):
    prompt = '(pandas-db) '
    intro = """
========================================================================
             Pandas 内存数据库交互式终端 (Pandas In-Memory DB CLI)
========================================================================
  code  <代码>      查看某个代码的全部交易记录
  summary           查看账户资金及交易盈亏总体总结
  query <表> <表达式>  筛选数据
  shell             进入 Python Shell
  help / ?          查看帮助
========================================================================
"""

    def __init__(self, dfs):
        super().__init__()
        self.dfs = dfs

    def emptyline(self):
        # 覆盖默认行为（即重复上一个命令）
        pass

    def _complete_table_name(self, text):
        return [t for t in self.dfs.keys() if t.lower().startswith(text.lower())]

    def do_query(self, arg):
        """使用 Pandas Query 表达式筛选数据：query <表名> <表达式>
示例: query Transaction_History "数量 > 100"
或者: query "Transaction History" "代码 == 'SGOV'"
        """
        import shlex
        try:
            args = shlex.split(arg)
        except Exception:
            args = arg.split(maxsplit=1)
            
        if len(args) < 2:
            print("错误: 用法: query <表名> <查询表达式>")
            print("例如: query \"Transaction History\" \"数量 > 100\"")
            return
            
        table_name = args[0]
        expr = args[1]
        
        if table_name not in self.dfs:
            matches = [t for t in self.dfs.keys() if table_name.lower() in t.lower()]
            if len(matches) == 1:
                table_name = matches[0]
            else:
                print(f"错误: 未找到表 '{table_name}'。")
                return
                
        df = self.dfs[table_name]
        try:
            result = df.query(expr)
            print(f"\n查询结果 (匹配到 {len(result)} 行):")
            print_dataframe_ascii(result)
            print()
        except Exception as e:
            print(f"查询出错: {e}")
            print("提示: 如果列名包含空格或特殊字符，请使用反引号括起来，例如: `Price Currency` == 'USD'")

    def complete_query(self, text, line, begidx, endidx):
        return self._complete_table_name(text)

    def do_sum(self, arg):
        """计算数值列的总和：sum <表名> <列名>"""
        args = arg.split()
        if len(args) < 2:
            print("用法: sum <表名> <列名>")
            return
        table_name = args[0].strip("'\"")
        col_name = " ".join(args[1:]).strip("'\"")

        if table_name not in self.dfs:
            print(f"错误: 未找到表 '{table_name}'。")
            return

        df = self.dfs[table_name]

        # 支持英文列名映射
        if col_name in HEADER_MAP:
            col_name = HEADER_MAP[col_name]
        else:
            for eng_key, chn_val in HEADER_MAP.items():
                if eng_key.lower() == col_name.lower():
                    col_name = chn_val
                    break

        if col_name not in df.columns:
            print(f"错误: 列 '{col_name}' 不存在。")
            return

        try:
            total = df[col_name].sum()
            print(f"\n表 '{table_name}' 的 '{col_name}' 列总和为: {total}\n")
        except Exception as e:
            print(f"计算失败 (可能该列不是数值列?): {e}")

    def complete_sum(self, text, line, begidx, endidx):
        return self._complete_table_name(text)

    def _complete_code_name(self, text):
        """为 code 命令提供代码名称的 Tab 自动补全。"""
        prefix = 'code/'
        return [
            k[len(prefix):] for k in self.dfs
            if k.startswith(prefix) and k[len(prefix):].lower().startswith(text.lower())
        ]

    def do_code(self, arg):
        """查看指定代码（含关联期权）的全部交易记录及当前持仓：code <代码>
示例: code SGOV
      code NVO"""
        symbol = arg.strip().upper()
        if not symbol:
            print('用法: code <代码>  例如: code NVO')
            return
        key = f'code/{symbol}'
        if key not in self.dfs:
            matches = [k for k in self.dfs if k.startswith('code/') and symbol in k.upper()]
            if len(matches) == 1:
                key = matches[0]
                symbol = key[len('code/'):]
            else:
                print(f"未找到代码 '{symbol}'。")
                if matches:
                    print('相似代码: ' + ', '.join(k[len('code/'):] for k in matches))
                return

        # ── 获取合并后的交易记录 ────────────
        combined_df = self.dfs[key].copy()
        if '日期' in combined_df.columns:
            combined_df = combined_df.sort_values('日期', ascending=False).reset_index(drop=True)

        # 区分股票和期权
        is_option = combined_df['代码'].astype(str).str.contains(' ', na=False)
        df_stock = combined_df[~is_option].copy()
        df_option = combined_df[is_option].copy()

        n_stock = len(df_stock)
        n_opt   = len(df_option)
        opt_symbols = df_option['代码'].unique() if n_opt > 0 else []
        opt_label = f'，含 {len(opt_symbols)} 张期权共 {n_opt} 笔' if n_opt > 0 else ''
        print(f"\n[{symbol}]  共 {len(combined_df)} 笔交易（股票 {n_stock} 笔{opt_label}）:")
        print_dataframe_ascii(combined_df, max_rows=len(combined_df))

        print()
        # ── 股票资金流水汇总 ───────────────────────────────────
        if not df_stock.empty and '净额' in df_stock.columns:
            buy_types = df_stock['交易类型'].isin(TRADE_TYPES) if '交易类型' in df_stock.columns else pd.Series(False, index=df_stock.index)
            trade_net = df_stock.loc[buy_types, '净额'].sum()
            other_net = df_stock.loc[~buy_types, '净额'].sum()
            print(f"  买卖净额合计   : {trade_net:.4f}  （仅买卖/行权）")
            print(f"  股息税费净额   : {other_net:.4f}  （股息、预扣税等）")
        if '佣金' in combined_df.columns:
            stock_comm = df_stock['佣金'].sum() if not df_stock.empty and '佣金' in df_stock.columns else 0.0
            opt_comm = df_option['佣金'].sum() if not df_option.empty and '佣金' in df_option.columns else 0.0
            print(f"  佣金合计       : {combined_df['佣金'].sum():.4f}  （股票 {stock_comm:.4f} + 期权 {opt_comm:.4f}）")

        # ── 持仓成本（加权平均成本法，仅基于股票记录）──────────
        cb = calc_cost_basis(df_stock)
        print(f"\n  {'─'*48}")
        if abs(cb['qty']) >= 0.0001:
            print(f"  当前净持仓数量 : {cb['qty']:+.4f} 股")
            print(f"  总持仓成本     : {cb['total_cost']:.4f} USD")
            print(f"  每股平均成本   : {cb['avg_cost']:.4f} USD/股")
            print(f"  全投入均价(股) : {cb['allin_avg']:.4f} USD/股  （含做T已实现盈亏）")
            if abs(cb['realized_pnl']) > 0.0001:
                print(f"  已实现盈亏(股) : {cb['realized_pnl']:+.4f} USD")

            # ── 含期权的全投入均价 ─────────────────────────────
            opt_details, opt_total = calc_option_net_from_df(combined_df, symbol)
            if opt_details:
                combined_allin_cost = cb['allin_cost'] - opt_total
                combined_allin_avg  = combined_allin_cost / cb['qty']
                print(f"  期权净权利金   : {opt_total:+.4f} USD（共 {len(opt_details)} 张）")
                print(f"  全投入均价(含期权): {combined_allin_avg:.4f} USD/股")

            # 按账户明细
            if not df_stock.empty and '数量' in df_stock.columns and '账户' in df_stock.columns:
                acct_qty = df_stock[df_stock['数量'].notna()].groupby('账户')['数量'].sum()
                if len(acct_qty) > 1:
                    print("\n  按账户持仓明细 :")
                    for acct, q in acct_qty.items():
                        print(f"    {acct}: {q:+.4f} 股")
        else:
            print(f"  当前净持仓数量 : 0（已全部平仓）")
            if abs(cb['realized_pnl']) > 0.0001:
                print(f"  已实现盈亏(股) : {cb['realized_pnl']:+.4f} USD")
            opt_details, opt_total = calc_option_net_from_df(combined_df, symbol)
            if opt_details:
                print(f"  期权净权利金   : {opt_total:+.4f} USD（共 {len(opt_details)} 张）")
        print()


    def complete_code(self, text, line, begidx, endidx):
        return self._complete_code_name(text)

    def do_summary(self, arg):
        """查看账户资金及交易盈亏总体总结：summary"""
        main_tables = {k: v for k, v in self.dfs.items()
                       if '代码' in v.columns and not k.startswith('code/')}
        if not main_tables:
            print("未找到含 '代码' 列的数据表。")
            return

        combined = pd.concat(main_tables.values(), ignore_index=True)
        if combined.empty:
            print("交易记录为空。")
            return

        # 1. 基础信息
        total_tx = len(combined)
        date_col = combined['日期'] if '日期' in combined.columns else pd.Series()
        date_range = ""
        if not date_col.empty:
            min_date = date_col.min()
            max_date = date_col.max()
            date_range = f"{min_date.strftime('%Y-%m-%d') if hasattr(min_date, 'strftime') else min_date} 至 {max_date.strftime('%Y-%m-%d') if hasattr(max_date, 'strftime') else max_date}"

        # 2. 收集每个代码的详细数据
        code_tables = {k: v for k, v in self.dfs.items() if k.startswith('code/')}
        rows = []

        # 累计值
        total_stock_qty = 0.0
        total_stock_cost = 0.0
        total_realized_pnl = 0.0
        total_opt_premium = 0.0
        total_net_sum = 0.0
        total_comm_sum = 0.0
        total_tx_count = 0
        total_combined_pnl = 0.0

        for key, df_code in sorted(code_tables.items()):
            sym = key[len('code/'):]
            # 区分股票和期权
            is_option = df_code['代码'].astype(str).str.contains(' ', na=False)
            df_stock = df_code[~is_option].copy()
            df_option = df_code[is_option].copy()

            # 股票持仓与成本
            cb = calc_cost_basis(df_stock)
            qty = cb.get('qty', 0.0)
            cost = cb.get('total_cost', 0.0)
            avg_cost = cb.get('avg_cost', 0.0)
            realized_pnl = cb.get('realized_pnl', 0.0)
            allin_cost = cb.get('allin_cost', 0.0)

            # 期权净权利金
            _, opt_premium = calc_option_net_from_df(df_code, sym)

            # 净额与佣金合计
            net_sum = df_code['净额'].sum() if '净额' in df_code.columns else 0.0
            comm_sum = df_code['佣金'].sum() if '佣金' in df_code.columns else 0.0

            # 交易笔数
            tx_count = len(df_code)

            # 已实现盈亏(含期权) = 股票已实现盈亏 + 期权净权利金
            combined_pnl = realized_pnl + opt_premium

            # 全投入均价(含期权)
            if abs(qty) >= 0.0001:
                combined_allin_avg = (allin_cost - opt_premium) / qty
            else:
                combined_allin_avg = 0.0

            rows.append({
                '代码': sym,
                '持仓数量': qty,
                '持仓成本': cost,
                '持仓均价': avg_cost,
                '已实现盈亏': realized_pnl,
                '期权权利金': opt_premium,
                '已实现盈亏(含期权)': combined_pnl,
                '全投入均价(含期权)': combined_allin_avg,
                '交易笔数': tx_count,
                '净额合计': net_sum,
                '佣金合计': comm_sum
            })

            total_stock_qty += qty
            total_stock_cost += cost
            total_realized_pnl += realized_pnl
            total_opt_premium += opt_premium
            total_combined_pnl += combined_pnl
            total_net_sum += net_sum
            total_comm_sum += comm_sum
            total_tx_count += tx_count

        # 分离持仓中和已平仓
        open_rows = [r for r in rows if abs(r['持仓数量']) >= 0.0001]
        closed_rows = [r for r in rows if abs(r['持仓数量']) < 0.0001]

        hdr = ['代码', '持仓数量', '持仓成本', '持仓均价', '全投入均价(含期权)', '已实现盈亏', '期权权利金', '已实现盈亏(含期权)', '交易笔数', '净额合计', '佣金合计']

        def dlen(s):
            try:
                return len(str(s).encode('gbk', errors='ignore'))
            except Exception:
                return len(str(s))

        def pad(s, w):
            return s + ' ' * max(0, w - dlen(s))

        def print_table(title, table_rows):
            if not table_rows:
                print(f"\n--- {title} (无数据) ---")
                return

            print(f"\n--- {title} (共 {len(table_rows)} 个代码) ---")

            t_qty = sum(r['持仓数量'] for r in table_rows)
            t_cost = sum(r['持仓成本'] for r in table_rows)
            t_realized = sum(r['已实现盈亏'] for r in table_rows)
            t_opt = sum(r['期权权利金'] for r in table_rows)
            t_combined = sum(r['已实现盈亏(含期权)'] for r in table_rows)
            t_tx = sum(r['交易笔数'] for r in table_rows)
            t_net = sum(r['净额合计'] for r in table_rows)
            t_comm = sum(r['佣金合计'] for r in table_rows)

            col_w = [dlen(h) for h in hdr]

            formatted_rows = []
            for r in table_rows:
                cells = [
                    r['代码'],
                    f"{r['持仓数量']:.4f}" if abs(r['持仓数量']) >= 0.0001 else '-',
                    f"{r['持仓成本']:.2f}" if abs(r['持仓数量']) >= 0.0001 else '-',
                    f"{r['持仓均价']:.4f}" if abs(r['持仓数量']) >= 0.0001 else '-',
                    f"{r['全投入均价(含期权)']:.4f}" if abs(r['持仓数量']) >= 0.0001 else '-',
                    f"{r['已实现盈亏']:+.2f}" if abs(r['已实现盈亏']) >= 0.01 else '-',
                    f"{r['期权权利金']:+.2f}" if abs(r['期权权利金']) >= 0.01 else '-',
                    f"{r['已实现盈亏(含期权)']:+.2f}" if abs(r['已实现盈亏(含期权)']) >= 0.01 else '-',
                    str(r['交易笔数']),
                    f"{r['净额合计']:+.2f}" if abs(r['净额合计']) >= 0.01 else '-',
                    f"{r['佣金合计']:.4f}" if abs(r['佣金合计']) >= 0.0001 else '-'
                ]
                formatted_rows.append(cells)
                for i, c in enumerate(cells):
                    col_w[i] = max(col_w[i], dlen(c))

            total_cells = [
                'TOTAL',
                f"{t_qty:.4f}" if abs(t_qty) >= 0.0001 else '-',
                f"{t_cost:.2f}" if abs(t_cost) >= 0.01 else '-',
                '-',
                '-',
                f"{t_realized:+.2f}" if abs(t_realized) >= 0.01 else '-',
                f"{t_opt:+.2f}" if abs(t_opt) >= 0.01 else '-',
                f"{t_combined:+.2f}" if abs(t_combined) >= 0.01 else '-',
                str(t_tx),
                f"{t_net:+.2f}" if abs(t_net) >= 0.01 else '-',
                f"{t_comm:.4f}" if abs(t_comm) >= 0.0001 else '-'
            ]
            for i, c in enumerate(total_cells):
                col_w[i] = max(col_w[i], dlen(c))

            sep = '+' + '+'.join('-' * (w + 2) for w in col_w) + '+'
            print(sep)
            print('| ' + ' | '.join(pad(h, col_w[i]) for i, h in enumerate(hdr)) + ' |')
            print(sep.replace('-', '='))

            for cells in formatted_rows:
                print('| ' + ' | '.join(pad(c, col_w[i]) for i, c in enumerate(cells)) + ' |')

            print(sep.replace('-', '='))
            # 打印 Total 行
            print('| ' + ' | '.join(pad(c, col_w[i]) for i, c in enumerate(total_cells)) + ' |')
            print(sep)

        print("\n======================================================================================================================================================")
        print("                                                               各代码交易及持仓明细")
        print("======================================================================================================================================================")

        print_table("已平仓 (Closed Positions)", closed_rows)
        print_table("持仓中 (Open Positions)", open_rows)
        print(f'共 {len(rows)} 个代码\n')

        # 更新累计值用于总体总结
        total_stock_cost = sum(r['持仓成本'] for r in open_rows)
        total_realized_pnl = sum(r['已实现盈亏'] for r in rows)
        total_opt_premium = sum(r['期权权利金'] for r in rows)
        total_combined_pnl = sum(r['已实现盈亏(含期权)'] for r in rows)
        total_net_sum = sum(r['净额合计'] for r in rows)
        total_comm_sum = sum(r['佣金合计'] for r in rows)
        total_tx_count = sum(r['交易笔数'] for r in rows)

        # 3. 佣金合计
        total_comm = 0.0
        stock_comm = 0.0
        opt_comm = 0.0
        if '佣金' in combined.columns:
            total_comm = combined['佣金'].sum()
            # 区分股票和期权佣金
            is_option = combined['代码'].astype(str).str.contains(' ', na=False)
            stock_comm = combined.loc[~is_option, '佣金'].sum()
            opt_comm = combined.loc[is_option, '佣金'].sum()

        # 4. 股息与预扣税
        total_dividend = 0.0
        total_withholding_tax = 0.0
        total_in_lieu = 0.0
        if '交易类型' in combined.columns and '净额' in combined.columns:
            total_dividend = combined.loc[combined['交易类型'] == '股息', '净额'].sum()
            total_withholding_tax = combined.loc[combined['交易类型'] == '外国预扣税', '净额'].sum()
            total_in_lieu = combined.loc[combined['交易类型'] == '替代支付', '净额'].sum()

        # 5. 利息
        total_interest = 0.0
        credit_interest = 0.0
        debit_interest = 0.0
        if '交易类型' in combined.columns and '净额' in combined.columns:
            credit_interest = combined.loc[combined['交易类型'] == '贷方利息', '净额'].sum()
            debit_interest = combined.loc[combined['交易类型'] == '借方利息', '净额'].sum()
            total_interest = credit_interest + debit_interest

        # 6. 资金转账
        total_deposit = 0.0
        total_withdrawal = 0.0
        if '交易类型' in combined.columns and '净额' in combined.columns:
            # 过滤掉说明为“现金转账”的内部互转记录，只统计外部出入金
            is_not_transfer = combined['说明'].astype(str) != '现金转账' if '说明' in combined.columns else pd.Series(True, index=combined.index)
            total_deposit = combined.loc[(combined['交易类型'] == '存款') & is_not_transfer, '净额'].sum()
            total_withdrawal = combined.loc[(combined['交易类型'] == '取款') & is_not_transfer, '净额'].sum()

        # 7. 其它费用与调整
        other_fees = 0.0
        adjustments = 0.0
        if '交易类型' in combined.columns and '净额' in combined.columns:
            other_fees = combined.loc[combined['交易类型'] == '其它费用', '净额'].sum()
            adjustments = combined.loc[combined['交易类型'].isin(['调整', '外汇交易组成部分']), '净额'].sum()

        print("========================================================================")
        print("                      账户资金及交易盈亏总体总结")
        print("========================================================================")
        if date_range:
            print(f"  时间范围       : {date_range}")
        print(f"  总交易笔数     : {total_tx} 笔")
        print("  ----------------------------------------------------------------------")
        print(f"  已实现盈亏(股) : {total_realized_pnl:+.2f} USD  (仅股票做T已实现盈亏)")
        print(f"  期权净权利金   : {total_opt_premium:+.2f} USD  (所有期权净现金流)")
        print(f"  股息净收入     : {total_dividend + total_withholding_tax + total_in_lieu:+.2f} USD  (股息 {total_dividend:+.2f} + 预扣税 {total_withholding_tax:+.2f} + 替代支付 {total_in_lieu:+.2f})")
        print(f"  利息净收入     : {total_interest:+.2f} USD  (贷方利息 {credit_interest:+.2f} + 借方利息 {debit_interest:+.2f})")
        print(f"  佣金合计       : {total_comm:.2f} USD  (股票 {stock_comm:.2f} + 期权 {opt_comm:.2f})")
        print(f"  其它费用与调整 : {other_fees + adjustments:+.2f} USD  (费用 {other_fees:+.2f} + 调整 {adjustments:+.2f})")
        print("  ----------------------------------------------------------------------")
        # 净盈亏 = 已实现盈亏 + 期权净权利金 + 股息净收入 + 利息净收入 + 其它费用与调整
        # 注：佣金已经包含在交易净额/已实现盈亏/期权净权利金中了，这里不需要重复扣除
        net_profit = total_realized_pnl + total_opt_premium + (total_dividend + total_withholding_tax + total_in_lieu) + total_interest + (other_fees + adjustments)
        print(f"  账户净盈亏合计 : {net_profit:+.2f} USD")
        print("  ----------------------------------------------------------------------")
        print(f"  资金转账合计   : {total_deposit + total_withdrawal:+.2f} USD  (存款 {total_deposit:+.2f} + 取款 {total_withdrawal:+.2f})")
        print("========================================================================\n")

    def do_save(self, arg):
        """将表保存为独立的 CSV 文件：save <表名> <输出文件路径>"""
        import shlex
        try:
            args = shlex.split(arg)
        except Exception:
            args = arg.split()
            
        if len(args) < 2:
            print("用法: save <表名> <输出文件路径>")
            return
            
        table_name = args[0]
        out_path = args[1]
        
        if table_name not in self.dfs:
            print(f"错误: 未找到表 '{table_name}'。")
            return
            
        try:
            self.dfs[table_name].to_csv(out_path, index=False, encoding='utf-8-sig')
            print(f"成功将表 '{table_name}' 保存至 '{out_path}'")
        except Exception as e:
            print(f"保存失败: {e}")

    def complete_save(self, text, line, begidx, endidx):
        return self._complete_table_name(text)

    def do_shell(self, arg):
        """进入原生 Python 交互式命令行，可以直接用 pandas 操作数据表"""
        print("\n正在启动交互式 Python 终端...")
        print("在这里您可以直接操作 pandas 变量:")
        print("  - 'dfs': 包含所有 DataFrame 的字典 (例如: dfs['Transaction History'])")
        print("  - 'pd': pandas 库对象")
        print("  - 我们也为表名注册了简短变量名 (例如: transaction_history 代表 Transaction History 表)")
        print("输入 exit() 或 ctrl-d 返回主菜单。\n")
        
        # 准备局部变量
        local_vars = {
            'dfs': self.dfs,
            'pd': pd
        }
        # 注册简写变量
        for name, df in self.dfs.items():
            safe_name = name.lower().replace(' ', '_').replace('-', '_')
            safe_name = ''.join(c for c in safe_name if c.isalnum() or c == '_')
            if safe_name.isidentifier():
                local_vars[safe_name] = df
                print(f"  已注册变量: {safe_name} (指向 '{name}')")
                
        print()
        code.interact(banner="", local=local_vars)
        print("\n已退出 Python Shell，返回交互命令行。")

    def do_exit(self, arg):
        """退出程序：exit"""
        print("再见！")
        return True

    def do_quit(self, arg):
        """退出程序：quit"""
        return self.do_exit(arg)

    def do_q(self, arg):
        """退出程序：q"""
        return self.do_exit(arg)

# 定义用户指定保留的字段
TARGET_COLUMNS = ['日期', '账户', '说明', '交易类型', '代码', '数量', '价格', 'Price Currency', '总额', '佣金', '净额']

# 英文表头到中文表头的映射
HEADER_MAP = {
    'Date': '日期',
    'Account': '账户',
    'Description': '说明',
    'Type': '交易类型',
    'Symbol': '代码',
    'Quantity': '数量',
    'Price': '价格',
    'Amount': '总额',
    'Commission': '佣金',
    'Net': '净额'
}

# 英文交易类型到中文交易类型的映射
TRADE_TYPE_MAP = {
    'Buy': '买',
    'Sell': '卖',
    'Assigned': '被行权',
    'Exercised': '行权',
    'Split': '拆股',
    'Dividend': '股息',
    'Withholding Tax': '外国预扣税',
    'Payment In Lieu': '替代支付',
    'Credit Interest': '贷方利息',
    'Debit Interest': '借方利息',
    'Deposit': '存款',
    'Withdrawal': '取款',
    'Other Fees': '其它费用',
    'Adjustment': '调整'
}

# 买卖相关的交易类型（用于成本计算，排除股息/税费等）
TRADE_TYPES = {'买', '卖', '被行权', '行权', '拆股', 'Split', 'Buy', 'Sell', 'Exercised', 'Assigned'}

def calc_cost_basis(df):
    """
    用加权平均成本法计算当前持仓成本。
    只统计交易类型为「买/卖/被行权/行权/拆股」且有数量的行。
    支持多头（Long）和空头（Short）持仓的成本及已实现盈亏计算，并支持仓位反转。

    返回 dict:
      qty          : 当前净持仓数量
      total_cost   : 当前总持仓成本（对多头为正，对空头为负，表示未平仓部分的资金占用/收入）
      avg_cost     : 每股平均持仓成本（绝对值）
      realized_pnl : 已实现盈亏（平仓收入 - 对应成本）
    """
    result = dict(qty=0.0, total_cost=0.0, avg_cost=0.0, realized_pnl=0.0)

    needed = {'数量', '净额', '交易类型', '日期'}
    if not needed.issubset(df.columns):
        return result

    # 只取买卖行，按日期升序
    trade_df = df[
        df['交易类型'].isin(TRADE_TYPES) & df['数量'].notna()
    ].copy()

    if trade_df.empty:
        return result

    # 保持同日期交易在 CSV 中的原始顺序（即反转后的正序），使用 stable sort
    trade_df = trade_df.sort_values('日期', kind='stable').reset_index(drop=True)

    running_qty  = 0.0   # 当前持仓数量
    running_cost = 0.0   # 当前持仓总成本（正数 = 花出去的钱，负数 = 卖空收到的钱）
    realized_pnl = 0.0

    for _, row in trade_df.iterrows():
        qty = float(row['数量'])
        net = float(row['净额']) if pd.notna(row['净额']) else 0.0
        t_type = row['交易类型']

        # 特殊处理拆股 (Split)
        if t_type in {'拆股', 'Split'}:
            running_qty += qty
            if abs(running_qty) < 1e-5:
                running_qty = 0.0
                running_cost = 0.0
            continue

        # 判断是否是平仓/减仓操作（即交易方向与当前持仓方向相反，且当前有持仓）
        is_closing = (running_qty > 1e-5 and qty < -1e-5) or (running_qty < -1e-5 and qty > 1e-5)

        if is_closing:
            # 减仓/平仓数量（取当前持仓和交易数量的较小值，方向与交易方向一致）
            close_qty = qty if abs(qty) <= abs(running_qty) else (-running_qty)
            # 剩余数量（如果交易数量大于当前持仓，则会发生仓位反转）
            rem_qty = qty - close_qty

            # 计算平仓部分所占的净额比例
            close_ratio = abs(close_qty) / abs(qty)
            close_net = net * close_ratio
            rem_net = net * (1 - close_ratio)

            # 计算平仓部分的成本
            avg_cost = running_cost / running_qty
            cost_of_closed = avg_cost * close_qty

            # 简化后的计算公式
            realized_pnl += close_net + cost_of_closed
            running_qty += close_qty
            running_cost += cost_of_closed

            # 确保 running_cost 不会因为浮点数精度问题变成微小的非零值，或者在完全平仓时归零
            if abs(running_qty) < 1e-5:
                running_qty = 0.0
                running_cost = 0.0

            # 处理仓位反转（例如从多头直接变成空头，或者空头直接变成多头）
            if abs(rem_qty) > 1e-5:
                running_qty = rem_qty
                # 反转后，新方向的初始成本就是剩余部分的净额绝对值
                running_cost = -rem_net
        else:
            # 开仓/加仓（方向相同或从零开始）
            running_qty += qty
            running_cost -= net
            if abs(running_qty) < 1e-5:
                running_qty = 0.0
                running_cost = 0.0

    result['qty']          = running_qty
    result['total_cost']   = abs(running_cost)
    result['avg_cost']     = abs(running_cost / running_qty) if running_qty != 0 else 0.0
    result['realized_pnl'] = realized_pnl
    # 全投入成本：把已实现盈亏（做T差价）也计入，反映真实现金投入
    allin_cost = abs(running_cost) - realized_pnl
    result['allin_cost']   = allin_cost
    result['allin_avg']    = allin_cost / running_qty if running_qty != 0 else 0.0
    return result

def get_underlying_symbol(symbol):
    """
    提取标的代码。期权代码格式为「标的代码 + 空格 + 日期/类型/行权价」，如 NVO   260102P00052000。
    """
    symbol_str = str(symbol).strip()
    if not symbol_str or symbol_str == '-' or symbol_str.lower() == 'nan':
        return '(出入金/利息/费用)'
    if ' ' in symbol_str:
        return symbol_str.split()[0]
    return symbol_str

def calc_option_net_from_df(df, underlying):
    """
    从包含股票和期权交易记录的 DataFrame 中汇总某标的所有关联期权的净现金流（权利金收/付之和）。
    返回: (details_dict, total_net)
      details_dict : {期权代码: 净现金流, ...}
      total_net    : 所有期权净现金流合计
    正值表示净收权利金（减少持仓成本），负值表示净付权利金（增加持仓成本）。
    """
    is_option = df['代码'].astype(str).str.contains(' ', na=False)
    df_option = df[is_option]

    details = {}
    if not df_option.empty:
        groups = df_option.groupby('代码')
        for opt_sym, group_df in groups:
            net = float(group_df['净额'].sum()) if '净额' in group_df.columns else 0.0
            details[str(opt_sym)] = net

    total = sum(details.values())
    return details, total

def group_by_code(all_dfs):
    """
    将含有 '代码' 列的表按标的代码分组（期权按标的归并到同一组），
    为每个标的代码生成独立的子 DataFrame，存入 all_dfs（键名格式为 'code/<标的代码>'），
    并打印启动汇总。
    """
    source_tables = {k: v for k, v in all_dfs.items()
                     if '代码' in v.columns and not k.startswith('code/')}
    if not source_tables:
        return

    for table_name, df in source_tables.items():
        # 提取标的代码作为分组键
        df_with_underlying = df.copy()
        df_with_underlying['underlying'] = df_with_underlying['代码'].apply(get_underlying_symbol)

        groups = df_with_underlying.groupby('underlying', sort=True)
        for underlying, group_df in groups:
            # 移除临时添加的 underlying 列
            clean_group_df = group_df.drop(columns=['underlying']).reset_index(drop=True)
            key = f'code/{underlying}'
            if key in all_dfs:
                all_dfs[key] = pd.concat([all_dfs[key], clean_group_df], ignore_index=True)
            else:
                all_dfs[key] = clean_group_df

    n_codes = len([k for k in all_dfs if k.startswith('code/')])
    print(f'\n按代码分类完成，共 {n_codes} 个代码。输入 summary 查看汇总，输入 code <代码> 查看详情。\n')

def filter_dataframe_columns(df):
    """
    只保留指定的字段。同时支持英文表头和英文交易类型的转换。
    如果不含任何指定的字段，则返回空的 DataFrame。
    """
    df = df.copy()
    # 1. 英文表头不区分大小写映射为中文
    rename_dict = {}
    for col in df.columns:
        col_lower = col.lower()
        for eng_key, chn_val in HEADER_MAP.items():
            if eng_key.lower() == col_lower:
                rename_dict[col] = chn_val
                break
    if rename_dict:
        df = df.rename(columns=rename_dict)

    # 2. 英文交易类型不区分大小写映射为中文
    if '交易类型' in df.columns:
        trade_type_map_lower = {k.lower(): v for k, v in TRADE_TYPE_MAP.items()}
        df['交易类型'] = df['交易类型'].apply(
            lambda x: trade_type_map_lower.get(str(x).strip().lower(), x)
            if pd.notna(x) and isinstance(x, str) else x
        )

    # 3. 过滤保留目标列
    cols_to_keep = [col for col in TARGET_COLUMNS if col in df.columns]
    if not cols_to_keep:
        return pd.DataFrame()
    return df[cols_to_keep]

def main():
    parser = argparse.ArgumentParser(description="Pandas 内存数据库导入与查询工具")
    parser.add_argument('--dir', '-d', type=str, default='.', help='CSV 文件所在目录 (默认为当前目录)')
    parser.add_argument('--no-convert', action='store_true', help='禁用自动数据类型转换')
    args = parser.parse_args()
    
    target_dir = os.path.abspath(args.dir)
    print(f"正在扫描目录: {target_dir} ...")
    
    if not os.path.isdir(target_dir):
        print(f"错误: 目录 '{target_dir}' 不存在。")
        sys.exit(1)
        
    csv_files = [os.path.join(target_dir, f) for f in os.listdir(target_dir) if f.lower().endswith('.csv')]
    
    if not csv_files:
        print(f"未在目录 '{target_dir}' 下找到任何 CSV 文件。")
        sys.exit(0)
        
    print(f"找到 {len(csv_files)} 个 CSV 文件，正在导入内存并筛选字段...")
    
    all_dfs = {}
    for filepath in csv_files:
        filename = os.path.basename(filepath)
        print(f" - 正在读取: {filename} ... ", end="", flush=True)
        try:
            if is_multi_section_csv(filepath):
                file_dfs = load_ibkr_csv(filepath)
                print(f"[多段式 IBKR CSV, 包含 {len(file_dfs)} 个原始表]")
            else:
                file_dfs = load_standard_csv(filepath)
                print(f"[标准 CSV]")
                
            for table_name, df in file_dfs.items():
                # 过滤得到目标字段
                df = filter_dataframe_columns(df)
                if df.empty:
                    # 如果该表不含任何需要的字段，直接忽略（如 Statement 和 总结）
                    continue
                
                # 自动转换列类型
                if not args.no_convert:
                    df = auto_convert_types(df)
                    
                if table_name in all_dfs:
                    # 尝试合并
                    try:
                        all_dfs[table_name] = pd.concat([all_dfs[table_name], df], ignore_index=True)
                    except Exception as e:
                        new_table_name = f"{table_name}_{Path(filepath).stem}"
                        all_dfs[new_table_name] = df
                else:
                    all_dfs[table_name] = df
        except Exception as e:
            print(f"[失败] 错误信息: {e}")
            
    if not all_dfs:
        print("错误: 没有包含指定字段的数据可导入。")
        sys.exit(1)
        
    # 按代码分组
    group_by_code(all_dfs)

    # 启动交互式终端
    shell = PandasShell(all_dfs)
    shell.cmdloop()

if __name__ == '__main__':
    main()
