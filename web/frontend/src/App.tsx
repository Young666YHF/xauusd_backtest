import { BrowserRouter, Routes, Route, useLocation, useNavigate } from 'react-router-dom';
import { Layout, Menu } from 'antd';
import {
  HomeOutlined,
  StockOutlined,
  LineChartOutlined,
  ThunderboltOutlined,
  DollarOutlined,
} from '@ant-design/icons';
import HomePage from './pages/HomePage';
import StrategyPage from './pages/StrategyPage';
import BacktestPage from './pages/BacktestPage';
import OptimizePage from './pages/OptimizePage';
import DollarTraderPage from './pages/DollarTraderPage';
import './App.css';

const { Sider, Content, Header } = Layout;

const menuItems = [
  { key: '/', icon: <HomeOutlined />, label: '首页' },
  { key: '/strategy', icon: <StockOutlined />, label: '策略说明' },
  { key: '/backtest', icon: <LineChartOutlined />, label: '回测分析' },
  { key: '/optimize', icon: <ThunderboltOutlined />, label: '参数优化' },
  { key: '/dollar-trader', icon: <DollarOutlined />, label: '美元策略' },
];

function AppContent() {
  const location = useLocation();
  const navigate = useNavigate();

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Sider
        width={200}
        style={{
          background: '#001529',
        }}
        breakpoint="lg"
        collapsedWidth="80"
      >
        <div className="logo">
          <span className="logo-text">XAUUSD</span>
        </div>
        <Menu
          theme="dark"
          mode="inline"
          selectedKeys={[location.pathname]}
          onClick={({ key }) => navigate(key)}
          items={menuItems.map((item) => ({
            key: item.key,
            icon: item.icon,
            label: item.label,
          }))}
        />
      </Sider>
      <Layout>
        <Header style={{ background: '#fff', padding: '0 24px' }}>
          <h1 style={{ margin: 0, fontSize: '20px' }}>
            XAUUSD 黄金量化交易回测系统
          </h1>
        </Header>
        <Content style={{ margin: '24px', background: '#f0f2f5' }}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/strategy" element={<StrategyPage />} />
            <Route path="/backtest" element={<BacktestPage />} />
            <Route path="/optimize" element={<OptimizePage />} />
            <Route path="/dollar-trader" element={<DollarTraderPage />} />
          </Routes>
        </Content>
      </Layout>
    </Layout>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AppContent />
    </BrowserRouter>
  );
}

export default App;
