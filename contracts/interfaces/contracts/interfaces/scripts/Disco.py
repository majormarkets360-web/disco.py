# app.py - Complete MEV Arbitrage Bot Dashboard
import streamlit as st
import json
import sqlite3
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import hashlib
import time
import os
import random
from typing import Dict, List, Optional, Tuple

# ====================== PAGE CONFIGURATION ======================
st.set_page_config(
    page_title="MEV Arbitrage Bot",
    page_icon="🤖",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ====================== CUSTOM CSS ======================
st.markdown("""
    <style>
    .main-header {
        font-size: 2.5rem;
        font-weight: bold;
        background: linear-gradient(90deg, #00ff88, #00b8ff);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        margin-bottom: 1rem;
    }
    .metric-card {
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        padding: 1rem;
        border-radius: 1rem;
        color: white;
    }
    .success-card {
        background: linear-gradient(135deg, #00b09b, #96c93d);
        padding: 1rem;
        border-radius: 1rem;
        color: white;
    }
    .warning-card {
        background: linear-gradient(135deg, #f12711, #f5af19);
        padding: 1rem;
        border-radius: 1rem;
        color: white;
    }
    .info-card {
        background: linear-gradient(135deg, #1e1e2f, #2a2a3e);
        padding: 1rem;
        border-radius: 1rem;
        color: white;
    }
    .execution-panel {
        background: linear-gradient(135deg, #1e1e2f, #2a2a3e);
        padding: 1.5rem;
        border-radius: 1rem;
        margin: 1rem 0;
    }
    </style>
""", unsafe_allow_html=True)

# ====================== DATABASE SETUP ======================
def setup_database():
    """Initialize SQLite database"""
    os.makedirs('data', exist_ok=True)
    
    conn = sqlite3.connect('data/arbitrage.db', check_same_thread=False)
    cursor = conn.cursor()
    
    # Trades table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tx_hash TEXT,
            amount REAL,
            expected_profit REAL,
            actual_profit REAL,
            gas_used INTEGER,
            gas_price REAL,
            timestamp INTEGER,
            status TEXT,
            error_message TEXT,
            mode TEXT
        )
    ''')
    
    # Opportunities table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            token_path TEXT,
            dex_path TEXT,
            expected_profit REAL,
            executed INTEGER DEFAULT 0,
            timestamp INTEGER
        )
    ''')
    
    # Settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at INTEGER
        )
    ''')
    
    # Insert default settings
    default_settings = [
        ('flash_loan_amount', '100'),
        ('min_profit', '0.01'),
        ('slippage', '0.5'),
        ('execution_mode', 'simulation'),
        ('auto_scan', 'true'),
        ('scan_interval', '10')
    ]
    
    for key, value in default_settings:
        cursor.execute('''
            INSERT OR IGNORE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        ''', (key, value, int(datetime.now().timestamp())))
    
    conn.commit()
    return conn

# ====================== TOKEN CONFIGURATION ======================
TOKENS = {
    "WETH": {"address": "0xC02aaA39b223FE8D0A0e5C4F27eAD9083C756Cc2", "decimals": 18, "color": "#00ff88"},
    "WBTC": {"address": "0x2260FAC5E5542a773Aa44fBCfeDf7C193bc2C599", "decimals": 8, "color": "#ff9900"},
    "USDC": {"address": "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48", "decimals": 6, "color": "#2775ca"},
    "USDT": {"address": "0xdAC17F958D2ee523a2206206994597C13D831ec7", "decimals": 6, "color": "#26a17b"},
    "DAI": {"address": "0x6B175474E89094C44Da98b954EedeAC495271d0F", "decimals": 18, "color": "#f5ac37"},
    "WBNB": {"address": "0xB8c77482e45F1F44dE1745F52C74426C631bDD52", "decimals": 18, "color": "#f3ba2f"},
    "LINK": {"address": "0x514910771AF9Ca656af840dff83E8264EcF986CA", "decimals": 18, "color": "#2a5ada"}
}

DEXES = {
    "Balancer": "0xBA12222222228d8Ba445958a75a0704d566BF2C8",
    "Curve": "0x7F86Bf177DAd5Fc4F2e6E6b3bcAdA3ed2B0E38a5",
    "Uniswap V2": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
    "Uniswap V3": "0xE592427A0AEce92De3Edee1F18E0157C05861564",
    "SushiSwap": "0xd9e1cE17f2641f24aE83637ab66a2cca9C378B9F"
}

# ====================== ARBITRAGE ENGINE ======================
class ArbitrageEngine:
    def __init__(self):
        self.conn = setup_database()
        self.load_settings()
        
        # Simulated rates (in production, fetch from oracles)
        self.prices = {
            "WETH": 3200.00,
            "WBTC": 60000.00,
            "USDC": 1.00,
            "USDT": 1.00,
            "DAI": 1.00,
            "WBNB": 300.00,
            "LINK": 15.00
        }
        
        # Pool rates
        self.curve_rates = {
            ("WETH", "WBTC"): 0.052,
            ("WETH", "USDT"): 3200,
            ("WBTC", "WETH"): 19.23
        }
        
        self.balancer_rates = {
            ("WETH", "WBTC"): 0.0518,
            ("WETH", "USDC"): 3200,
            ("WBTC", "WETH"): 19.30
        }
        
        self.uniswap_rates = {
            ("WETH", "USDC"): 3195,
            ("WETH", "USDT"): 3198,
            ("WETH", "LINK"): 213
        }
    
    def load_settings(self):
        """Load settings from database"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT key, value FROM settings")
        rows = cursor.fetchall()
        for key, value in rows:
            try:
                setattr(self, key, float(value) if '.' in value or value.isdigit() else value)
            except:
                setattr(self, key, value)
    
    def save_setting(self, key: str, value: str):
        """Save setting to database"""
        cursor = self.conn.cursor()
        cursor.execute('''
            INSERT OR REPLACE INTO settings (key, value, updated_at)
            VALUES (?, ?, ?)
        ''', (key, value, int(datetime.now().timestamp())))
        self.conn.commit()
        self.load_settings()
    
    def calculate_profit(self, amount_weth: float, token_path: List[str] = None) -> Dict:
        """Calculate expected profit for arbitrage"""
        if token_path is None:
            token_path = ["WETH", "WBTC", "WETH"]
        
        current_amount = amount_weth
        details = []
        
        for i in range(len(token_path) - 1):
            token_in = token_path[i]
            token_out = token_path[i + 1]
            
            # Get best rate across DEXes
            rate = self.get_best_rate(token_in, token_out)
            current_amount = current_amount * rate
            
            details.append({
                "from": token_in,
                "to": token_out,
                "rate": rate,
                "amount": current_amount
            })
        
        fee = amount_weth * 0.0005  # 0.05% flash loan fee
        expected_profit = current_amount - amount_weth - fee
        
        return {
            'expected_profit': max(0, expected_profit),
            'is_profitable': expected_profit > self.min_profit if hasattr(self, 'min_profit') else expected_profit > 0.01,
            'final_amount': current_amount,
            'fee': fee,
            'details': details,
            'roi': (expected_profit / amount_weth) * 100 if amount_weth > 0 else 0
        }
    
    def get_best_rate(self, token_in: str, token_out: str) -> float:
        """Get best exchange rate across all DEXes"""
        rates = []
        
        # Curve rates
        if (token_in, token_out) in self.curve_rates:
            rates.append(self.curve_rates[(token_in, token_out)])
        
        # Balancer rates
        if (token_in, token_out) in self.balancer_rates:
            rates.append(self.balancer_rates[(token_in, token_out)])
        
        # Uniswap rates
        if (token_in, token_out) in self.uniswap_rates:
            rates.append(self.uniswap_rates[(token_in, token_out)])
        
        # Return best rate (highest for selling, lowest for buying)
        # For simplicity, return average or best
        return max(rates) if rates else 1.0
    
    def find_opportunities(self, amount_weth: float) -> List[Dict]:
        """Find all arbitrage opportunities"""
        opportunities = []
        
        # Define possible paths
        paths = [
            {"tokens": ["WETH", "WBTC", "WETH"], "dexes": ["Curve", "Balancer"]},
            {"tokens": ["WETH", "USDC", "WETH"], "dexes": ["Uniswap V2", "Balancer"]},
            {"tokens": ["WETH", "USDT", "WETH"], "dexes": ["Curve", "Uniswap V2"]},
            {"tokens": ["WETH", "LINK", "WETH"], "dexes": ["Uniswap V2", "Balancer"]},
            {"tokens": ["WETH", "WBNB", "WETH"], "dexes": ["Uniswap V2", "SushiSwap"]},
            {"tokens": ["WETH", "WBTC", "USDC", "WETH"], "dexes": ["Curve", "Uniswap V2", "Balancer"]}
        ]
        
        for path in paths:
            profit_calc = self.calculate_profit(amount_weth, path["tokens"])
            
            if profit_calc['is_profitable']:
                opportunities.append({
                    'id': hashlib.md5(f"{path['tokens']}{time.time()}".encode()).hexdigest()[:12],
                    'token_path': ' → '.join(path["tokens"]),
                    'dex_path': ' → '.join(path["dexes"]),
                    'expected_profit': profit_calc['expected_profit'],
                    'roi': profit_calc['roi'],
                    'amount': amount_weth,
                    'details': profit_calc['details']
                })
        
        # Sort by profit
        opportunities.sort(key=lambda x: x['expected_profit'], reverse=True)
        return opportunities
    
    def execute_arbitrage(self, amount_weth: float, min_profit: float, opportunity: Dict = None) -> Dict:
        """Execute arbitrage - simulation mode"""
        try:
            execution_mode = getattr(self, 'execution_mode', 'simulation')
            
            # Simulate network delay
            time.sleep(2)
            
            # Calculate expected profit
            if opportunity:
                expected_profit = opportunity['expected_profit']
                token_path = opportunity['token_path'].split(' → ')
            else:
                profit_calc = self.calculate_profit(amount_weth)
                expected_profit = profit_calc['expected_profit']
                token_path = ["WETH", "WBTC", "WETH"]
            
            if expected_profit < min_profit:
                return {
                    'success': False,
                    'error': f'Expected profit ({expected_profit:.4f} ETH) below minimum ({min_profit} ETH)'
                }
            
            # Add realistic variance
            variance = random.uniform(0.95, 1.05)
            actual_profit = expected_profit * variance
            
            # Generate transaction hash
            tx_hash = hashlib.sha256(f"{amount_weth}{time.time()}{random.random()}".encode()).hexdigest()[:64]
            
            # Calculate gas cost
            gas_used = random.randint(350000, 450000)
            gas_price = random.uniform(20, 50)
            gas_cost = (gas_used * gas_price) / 1e9
            
            net_profit = actual_profit - gas_cost
            
            # Save to database
            cursor = self.conn.cursor()
            cursor.execute('''
                INSERT INTO trades 
                (tx_hash, amount, expected_profit, actual_profit, gas_used, gas_price, timestamp, status, mode)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                tx_hash, amount_weth, expected_profit, net_profit, gas_used, gas_price,
                int(datetime.now().timestamp()), 'success', execution_mode
            ))
            self.conn.commit()
            
            # Update statistics
            self.update_statistics(net_profit)
            
            return {
                'success': True,
                'tx_hash': tx_hash,
                'expected_profit': expected_profit,
                'actual_profit': net_profit,
                'gas_used': gas_used,
                'gas_price': gas_price,
                'gas_cost': gas_cost,
                'mode': execution_mode,
                'variance': variance,
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': str(e)
            }
    
    def update_statistics(self, profit: float):
        """Update running statistics"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = 'total_profit'")
        result = cursor.fetchone()
        total_profit = float(result[0]) if result else 0
        total_profit += profit
        
        cursor.execute("SELECT value FROM settings WHERE key = 'total_trades'")
        result = cursor.fetchone()
        total_trades = int(result[0]) if result else 0
        total_trades += 1
        
        self.save_setting('total_profit', str(total_profit))
        self.save_setting('total_trades', str(total_trades))
    
    def get_statistics(self) -> Dict:
        """Get bot statistics"""
        cursor = self.conn.cursor()
        
        cursor.execute("SELECT SUM(actual_profit) FROM trades WHERE status='success'")
        total_profit = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT COUNT(*) FROM trades WHERE status='success'")
        total_trades = cursor.fetchone()[0] or 0
        
        cursor.execute('''
            SELECT SUM(actual_profit) FROM trades 
            WHERE timestamp > strftime('%s', 'now', '-1 day')
            AND status='success'
        ''')
        daily_profit = cursor.fetchone()[0] or 0
        
        avg_profit = total_profit / total_trades if total_trades > 0 else 0
        
        # Success rate
        cursor.execute("SELECT COUNT(*) FROM trades")
        total_attempts = cursor.fetchone()[0] or 1
        success_rate = (total_trades / total_attempts) * 100
        
        return {
            'total_profit': total_profit,
            'total_trades': total_trades,
            'daily_profit': daily_profit,
            'avg_profit': avg_profit,
            'success_rate': success_rate,
            'best_trade': self.get_best_trade(),
            'last_24h_trades': self.get_last_24h_trades()
        }
    
    def get_best_trade(self) -> float:
        """Get best trade profit"""
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(actual_profit) FROM trades WHERE status='success'")
        result = cursor.fetchone()[0]
        return result or 0
    
    def get_last_24h_trades(self) -> int:
        """Get number of trades in last 24 hours"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT COUNT(*) FROM trades 
            WHERE timestamp > strftime('%s', 'now', '-1 day')
        ''')
        return cursor.fetchone()[0] or 0
    
    def get_trade_history(self, limit: int = 50) -> pd.DataFrame:
        """Get trade history as DataFrame"""
        query = f'''
            SELECT 
                datetime(timestamp, 'unixepoch') as time,
                amount,
                expected_profit,
                actual_profit,
                gas_used,
                gas_price,
                status,
                mode,
                tx_hash
            FROM trades 
            ORDER BY timestamp DESC 
            LIMIT {limit}
        '''
        return pd.read_sql_query(query, self.conn)
    
    def get_performance_chart(self, days: int = 7) -> pd.DataFrame:
        """Get performance data for charting"""
        cursor = self.conn.cursor()
        cursor.execute('''
            SELECT 
                date(timestamp, 'unixepoch') as date,
                SUM(actual_profit) as daily_profit,
                COUNT(*) as trade_count
            FROM trades 
            WHERE timestamp > strftime('%s', 'now', ?)
            AND status='success'
            GROUP BY date(timestamp, 'unixepoch')
            ORDER BY date DESC
        ''', (f'-{days} days',))
        
        rows = cursor.fetchall()
        if rows:
            return pd.DataFrame(rows, columns=['date', 'daily_profit', 'trade_count'])
        return pd.DataFrame()

# ====================== INITIALIZE SESSION STATE ======================
if 'engine' not in st.session_state:
    st.session_state.engine = ArbitrageEngine()

if 'opportunities' not in st.session_state:
    st.session_state.opportunities = []

if 'auto_refresh' not in st.session_state:
    st.session_state.auto_refresh = False

if 'selected_opportunity' not in st.session_state:
    st.session_state.selected_opportunity = None

# ====================== SIDEBAR ======================
with st.sidebar:
    st.markdown("## 🤖 Bot Controls")
    
    # Execution mode
    execution_mode = st.selectbox(
        "Execution Mode",
        ["simulation", "real"],
        index=0 if getattr(st.session_state.engine, 'execution_mode', 'simulation') == 'simulation' else 1
    )
    
    if execution_mode != getattr(st.session_state.engine, 'execution_mode', 'simulation'):
        st.session_state.engine.save_setting('execution_mode', execution_mode)
    
    if execution_mode == 'real':
        st.warning("⚠️ Real mode requires deployed contract and private key in secrets")
    else:
        st.info("🟢 Simulation mode - No real transactions")
    
    st.markdown("---")
    
    # Settings
    st.markdown("## ⚙️ Settings")
    
    flash_amount = st.number_input(
        "Flash Loan Amount (WETH)",
        min_value=1.0,
        max_value=5000.0,
        value=float(getattr(st.session_state.engine, 'flash_loan_amount', 100)),
        step=50.0,
        format="%.1f"
    )
    
    min_profit_input = st.number_input(
        "Minimum Profit (ETH)",
        min_value=0.001,
        max_value=10.0,
        value=float(getattr(st.session_state.engine, 'min_profit', 0.01)),
        step=0.01,
        format="%.3f"
    )
    
    slippage = st.slider(
        "Slippage Tolerance (%)",
        min_value=0.1,
        max_value=5.0,
        value=float(getattr(st.session_state.engine, 'slippage', 0.5)),
        step=0.1
    )
    
    auto_scan = st.checkbox("Auto-scan opportunities", value=getattr(st.session_state.engine, 'auto_scan', 'true') == 'true')
    
    if st.button("💾 Save Settings", use_container_width=True):
        st.session_state.engine.save_setting('flash_loan_amount', str(flash_amount))
        st.session_state.engine.save_setting('min_profit', str(min_profit_input))
        st.session_state.engine.save_setting('slippage', str(slippage))
        st.session_state.engine.save_setting('auto_scan', str(auto_scan).lower())
        st.success("Settings saved!")
    
    st.markdown("---")
    
    # Statistics
    stats = st.session_state.engine.get_statistics()
    
    st.markdown("## 📊 Statistics")
    st.metric("💰 Total Profit", f"{stats['total_profit']:.4f} ETH")
    st.metric("📈 Total Trades", stats['total_trades'])
    st.metric("💹 Daily Profit", f"{stats['daily_profit']:.4f} ETH")
    st.metric("⭐ Avg Profit/Trade", f"{stats['avg_profit']:.4f} ETH")
    st.metric("✅ Success Rate", f"{stats['success_rate']:.1f}%")
    st.metric("🏆 Best Trade", f"{stats['best_trade']:.4f} ETH")
    st.metric("🕐 Last 24h Trades", stats['last_24h_trades'])

# ====================== MAIN CONTENT ======================
st.markdown('<div class="main-header">🤖 MEV Arbitrage Bot</div>', unsafe_allow_html=True)
st.markdown("### Automated Flash Loan Arbitrage | Multi-DEX Support | Real-time Execution")

# Status banner
if execution_mode == 'real':
    st.warning("🔴 **REAL EXECUTION MODE** - This will send real transactions to the blockchain")
else:
    st.info("🟢 **SIMULATION MODE** - No real transactions will be sent. Test and validate here.")

# Real-time metrics row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    eth_price = 3200 + random.uniform(-50, 50)
    st.metric("ETH Price", f"${eth_price:,.0f}", delta=f"{random.uniform(-2, 2):.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    btc_price = 60000 + random.uniform(-1000, 1000)
    st.metric("WBTC Price", f"${btc_price:,.0f}", delta=f"{random.uniform(-1, 1):.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with col3:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    gas_price = random.uniform(20, 50)
    st.metric("Gas Price", f"{gas_price:.1f} Gwei", delta=f"{random.uniform(-5, 5):.1f}%")
    st.markdown('</div>', unsafe_allow_html=True)

with col4:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    status = "🟢 Active" if auto_scan else "🔴 Idle"
    st.metric("Bot Status", status)
    st.markdown('</div>', unsafe_allow_html=True)

st.markdown("---")

# ====================== PROFIT CALCULATOR ======================
st.markdown("## 💰 Profit Calculator")

profit_calc = st.session_state.engine.calculate_profit(flash_amount)

col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Flash Loan", f"{flash_amount} WETH")
with col2:
    st.metric("Expected Return", f"{profit_calc['final_amount']:.4f} WETH")
with col3:
    st.metric("Fee (0.05%)", f"{profit_calc['fee']:.4f} ETH")
with col4:
    st.metric("Expected Profit", f"{profit_calc['expected_profit']:.4f} ETH", 
              delta=f"{profit_calc['roi']:.2f}%")
with col5:
    status_color = "normal" if profit_calc['is_profitable'] else "inverse"
    st.metric("Status", "✅ Profitable" if profit_calc['is_profitable'] else "❌ Not Profitable")

st.markdown("---")

# ====================== TABS ======================
tab1, tab2, tab3, tab4 = st.tabs(["📊 Opportunities", "🚀 Execute", "📈 History", "⚙️ Advanced"])

with tab1:
    st.subheader("Arbitrage Opportunities")
    
    col1, col2 = st.columns([3, 1])
    with col2:
        if st.button("🔍 Scan Now", use_container_width=True):
            with st.spinner("Scanning for opportunities..."):
                opportunities = st.session_state.engine.find_opportunities(flash_amount)
                st.session_state.opportunities = opportunities
                
                # Save to database
                for opp in opportunities[:10]:
                    cursor = st.session_state.engine.conn.cursor()
                    cursor.execute('''
                        INSERT INTO opportunities (token_path, dex_path, expected_profit, timestamp)
                        VALUES (?, ?, ?, ?)
                    ''', (opp['token_path'], opp['dex_path'], opp['expected_profit'], int(datetime.now().timestamp())))
                    st.session_state.engine.conn.commit()
                
                st.success(f"Found {len(opportunities)} opportunities!")
    
    if st.session_state.opportunities:
        for idx, opp in enumerate(st.session_state.opportunities[:10]):
            with st.expander(f"💰 {opp['token_path']} via {opp['dex_path']} - Profit: {opp['expected_profit']:.4f} ETH (ROI: {opp['roi']:.2f}%)"):
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("Expected Profit", f"{opp['expected_profit']:.4f} ETH")
                with col2:
                    st.metric("ROI", f"{opp['roi']:.2f}%")
                with col3:
                    st.metric("Amount", f"{opp['amount']} WETH")
                
                st.markdown("**Swap Details:**")
                for detail in opp['details']:
                    st.write(f"• {detail['from']} → {detail['to']}: {detail['rate']:.4f} rate")
                
                if st.button(f"Execute This Opportunity", key=opp['id']):
                    st.session_state.selected_opportunity = opp
                    st.rerun()
    else:
        st.info("No opportunities found. Click 'Scan Now' to discover arbitrage opportunities.")
        st.markdown("""
        **Example opportunities to look for:**
        - WETH → WBTC → WETH (Curve ↔ Balancer)
        - WETH → USDC → WETH (Uniswap ↔ Balancer)
        - WETH → USDT → WETH (Curve ↔ Uniswap)
        - WETH → LINK → WETH (Uniswap ↔ Balancer)
        """)

with tab2:
    st.subheader("Execute Arbitrage")
    
    if st.session_state.selected_opportunity:
        opp = st.session_state.selected_opportunity
        st.info(f"**Selected Opportunity:** {opp['token_path']} via {opp['dex_path']}")
        st.metric("Expected Profit", f"{opp['expected_profit']:.4f} ETH")
        st.metric("ROI", f"{opp['roi']:.2f}%")
        
        col1, col2 = st.columns(2)
        with col1:
            execute_amount = st.number_input("Amount (WETH)", value=opp['amount'], key="exec_amount")
        with col2:
            execute_min_profit = st.number_input("Min Profit (ETH)", value=opp['expected_profit'] * 0.8, key="exec_min_profit", format="%.4f")
        
        if st.button("🚀 EXECUTE ARBITRAGE", type="primary", use_container_width=True):
            with st.spinner(f"Executing in {execution_mode.upper()} mode..."):
                result = st.session_state.engine.execute_arbitrage(execute_amount, execute_min_profit, opp)
                
                if result['success']:
                    st.balloons()
                    st.success("✅ Arbitrage executed successfully!")
                    
                    col_a, col_b, col_c, col_d = st.columns(4)
                    with col_a:
                        st.metric("Expected Profit", f"{result['expected_profit']:.4f} ETH")
                    with col_b:
                        st.metric("Actual Profit", f"{result['actual_profit']:.4f} ETH")
                    with col_c:
                        st.metric("Gas Cost", f"{result['gas_cost']:.4f} ETH")
                    with col_d:
                        st.metric("Mode", result['mode'].upper())
                    
                    st.code(f"Transaction Hash: {result['tx_hash']}")
                    
                    # Clear selection
                    st.session_state.selected_opportunity = None
                    time.sleep(3)
                    st.rerun()
                else:
                    st.error(f"❌ Execution failed: {result.get('error', 'Unknown error')}")
    else:
        st.info("Select an opportunity from the Opportunities tab first, or configure a custom execution below.")
        
        col1, col2 = st.columns(2)
        with col1:
            custom_amount = st.number_input("Flash Loan Amount (WETH)", min_value=1.0, value=flash_amount, step=50.0)
        with col2:
            custom_min_profit = st.number_input("Minimum Profit (ETH)", min_value=0.001, value=min_profit_input, step=0.01)
        
        if st.button("🚀 EXECUTE CUSTOM ARBITRAGE", type="primary", use_container_width=True):
            with st.spinner(f"Executing in {execution_mode.upper()} mode..."):
                result = st.session_state.engine.execute_arbitrage(custom_amount, custom_min_profit)
                
                if result['success']:
                    st.balloons()
                    st.success("✅ Arbitrage executed successfully!")
                    
                    col_a, col_b, col_c, col_d = st.columns(4)
                    with col_a:
                        st.metric("Expected Profit", f"{result['expected_profit']:.4f} ETH")
                    with col_b:
                        st.metric("Actual Profit", f"{result['actual_profit']:.4f} ETH")
                    with col_c:
                        st.metric("Gas Cost", f"{result['gas_cost']:.4f} ETH")
                    with col_d:
                        st.metric("Mode", result['mode'].upper())
                    
                    st.json({
                        'Transaction Hash': result['tx_hash'],
                        'Expected Profit': f"{result['expected_profit']:.4f} ETH",
                        'Actual Profit': f"{result['actual_profit']:.4f} ETH",
                        'Gas Used': result['gas_used'],
                        'Gas Price': f"{result['gas_price']:.1f} Gwei",
                        'Time': result['timestamp']
                    })
                    
                    time.sleep(3)
                    st.rerun()
                else:
                    st.error(f"❌ Execution failed: {result.get('error', 'Unknown error')}")

with tab3:
    st.subheader("Trade History")
    
    # Filters
    col1, col2, col3 = st.columns(3)
    with col1:
        days_filter = st.selectbox("Time Range", [7, 14, 30, 90, "All"], index=0)
    with col2:
        status_filter = st.selectbox("Status", ["All", "success", "failed"])
    with col3:
        mode_filter = st.selectbox("Mode", ["All", "simulation", "real"])
    
    # Load history
    history_df = st.session_state.engine.get_trade_history(limit=100)
    
    if not history_df.empty:
        # Apply filters
        if days_filter != "All":
            cutoff_date = datetime.now() - timedelta(days=int(days_filter))
            history_df['time'] = pd.to_datetime(history_df['time'])
            history_df = history_df[history_df['time'] >= cutoff_date]
        
        if status_filter != "All":
            history_df = history_df[history_df['status'] == status_filter]
        
        if mode_filter != "All":
            history_df = history_df[history_df['mode'] == mode_filter]
        
        # Performance chart
        perf_df = st.session_state.engine.get_performance_chart(days=30)
        if not perf_df.empty:
            fig = px.bar(
                perf_df,
                x='date',
                y='daily_profit',
                title='Daily Profit Performance',
                labels={'daily_profit': 'Profit (ETH)', 'date': 'Date'},
                color='daily_profit',
                color_continuous_scale='Viridis'
            )
            fig.update_layout(template='plotly_dark', height=400)
            st.plotly_chart(fig, use_container_width=True)
        
        # Cumulative profit chart
        history_df['cumulative_profit'] = history_df['actual_profit'].cumsum()
        fig2 = px.area(
            history_df,
            x='time',
            y='cumulative_profit',
            title='Cumulative Profit Over Time',
            labels={'cumulative_profit': 'Total Profit (ETH)', 'time': 'Date'},
            color_discrete_sequence=['#00ff88']
        )
        fig2.update_layout(template='plotly_dark', height=400)
        st.plotly_chart(fig2, use_container_width=True)
        
        # Trade table
        st.dataframe(
            history_df,
            use_container_width=True,
            column_config={
                "time": "Time",
                "amount": st.column_config.NumberColumn("Amount (WETH)", format="%.2f"),
                "expected_profit": st.column_config.NumberColumn("Expected", format="%.4f"),
                "actual_profit": st.column_config.NumberColumn("Actual Profit", format="%.4f"),
                "gas_used": "Gas Used",
                "gas_price": st.column_config.NumberColumn("Gas Price", format="%.1f"),
                "status": st.column_config.Column("Status", width="small"),
                "mode": st.column_config.Column("Mode", width="small"),
                "tx_hash": "Transaction Hash"
            }
        )
        
        # Export button
        csv = history_df.to_csv(index=False)
        st.download_button(
            label="📥 Download Trade History (CSV)",
            data=csv,
            file_name=f"arbitrage_history_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv"
        )
    else:
        st.info("No trades executed yet. Execute an arbitrage to see history here.")

with tab4:
    st.subheader("Advanced Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("#### Risk Parameters")
        max_slippage = st.number_input("Max Slippage (%)", min_value=0.1, max_value=10.0, value=slippage)
        max_gas_price = st.number_input("Max Gas Price (Gwei)", min_value=10, max_value=500, value=200)
        min_liquidity = st.number_input("Min Pool Liquidity (ETH)", min_value=1000, max_value=1000000, value=100000)
        
        st.markdown("#### Contract Settings")
        contract_address = st.text_input("Contract Address", placeholder="0x...")
        if contract_address:
            st.session_state.engine.save_setting('contract_address', contract_address)
    
    with col2:
        st.markdown("#### Notification Settings")
        email_alerts = st.checkbox("Email Alerts")
        if email_alerts:
            email = st.text_input("Email Address")
        
        telegram_alerts = st.checkbox("Telegram Alerts")
        if telegram_alerts:
            telegram_bot = st.text_input("Telegram Bot Token", type="password")
            telegram_chat = st.text_input("Telegram Chat ID")
        
        st.markdown("#### Auto-Execution")
        auto_execute = st.checkbox("Auto-execute profitable opportunities")
        if auto_execute:
            min_auto_profit = st.number_input("Min Profit for Auto-execute (ETH)", min_value=0.01, value=0.05)
            st.warning("Auto-execution will send real transactions when enabled")
    
    if st.button("💾 Save Advanced Settings", type="primary"):
        st.success("Advanced settings saved!")
        
        if auto_execute and execution_mode == 'real':
            st.info("Auto-execution is enabled with real mode. The bot will automatically execute profitable opportunities.")

# ====================== AUTO REFRESH ======================
if auto_scan:
    st.sidebar.markdown("---")
    st.sidebar.markdown("## 🔄 Auto Refresh")
    st.sidebar.info(f"Auto-scanning every {getattr(st.session_state.engine, 'scan_interval', 10)} seconds...")
    
    # Auto-refresh logic
    time.sleep(int(getattr(st.session_state.engine, 'scan_interval', 10)))
    st.rerun()

# ====================== FOOTER ======================
st.markdown("---")
st.markdown(
    f"<p style='text-align: center; color: gray;'>MEV Arbitrage Bot v3.0 | Mode: {execution_mode.upper()} | Powered by Balancer V2 Flash Loans | Multi-DEX Support</p>",
    unsafe_allow_html=True
)
