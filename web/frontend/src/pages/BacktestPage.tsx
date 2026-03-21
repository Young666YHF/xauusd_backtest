import React, { useState, useEffect } from 'react';
import {
  Card,
  Row,
  Col,
  Form,
  InputNumber,
  Button,
  Spin,
  message,
  Table,
  Statistic,
  Space,
  Select,
  Modal,
  Input,
  Alert,
  Divider,
  Dropdown,
  Checkbox,
} from 'antd';
import {
  PlayCircleOutlined,
  ReloadOutlined,
  SaveOutlined,
  DeleteOutlined,
  FolderOutlined,
  SettingOutlined,
} from '@ant-design/icons';
import ReactECharts from 'echarts-for-react';
import { backtestApi } from '../api/client';
import type {
  BacktestResponse,
  BacktestResult,
  ConfigResponse,
  ParameterPreset,
} from '../types';

const PRESET_STORAGE_KEY = 'xauusd_backtest_presets';

const BacktestPage: React.FC = () => {
  const [form] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [config, setConfig] = useState<ConfigResponse | null>(null);
  const [result, setResult] = useState<BacktestResponse | null>(null);
  const [presets, setPresets] = useState<ParameterPreset[]>([]);
  const [presetModalVisible, setPresetModalVisible] = useState(false);
  const [presetName, setPresetName] = useState('');
  const [presetDesc, setPresetDesc] = useState('');
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(null);

  useEffect(() => {
    // 清除可能存在的脏 localStorage 数据
    try {
      const stored = localStorage.getItem(PRESET_STORAGE_KEY);
      if (stored) {
        const parsed = JSON.parse(stored);
        // 如果 localStorage 中有 server_ 开头的预设，说明数据已脏，清除它
        if (Array.isArray(parsed) && parsed.some((p: ParameterPreset) => p.id.startsWith('server_'))) {
          localStorage.removeItem(PRESET_STORAGE_KEY);
        }
      }
    } catch (e) {
      localStorage.removeItem(PRESET_STORAGE_KEY);
    }

    loadConfig();
    loadPresets();
  }, []);

  const loadConfig = async () => {
    try {
      const configData = await backtestApi.getConfig();
      setConfig(configData);
      form.setFieldsValue({
        parameters: configData.default_params,
        start_date: '2025-08-01',
        end_date: '2026-02-28',
        interval: '15m',
        initial_capital: 100000,
        position_size: 1.0,
        use_tick_backtest: true,
      });
    } catch (error) {
      message.error('加载配置失败');
    }
  };

  const loadPresets = async () => {
    try {
      // 从后端加载预设参数
      const response = await fetch('/api/presets');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }
      const data = await response.json();

      // 转换后端预设为前端格式
      const serverPresetList: ParameterPreset[] = [];
      if (data.presets) {
        for (const [name, preset] of Object.entries(data.presets)) {
          serverPresetList.push({
            id: `server_${name}`,
            name: name,
            description: (preset as any).description || '',
            parameters: (preset as any).params,
            created_at: (preset as any).created_at || '',
          });
        }
      }

      // 从本地存储加载用户自定义预设
      let localPresets: ParameterPreset[] = [];
      try {
        const stored = localStorage.getItem(PRESET_STORAGE_KEY);
        if (stored) {
          const parsed = JSON.parse(stored);
          if (Array.isArray(parsed)) {
            localPresets = parsed.filter((p: ParameterPreset) => !p.id.startsWith('server_'));
          }
        }
      } catch (e) {
        // 忽略解析错误
      }

      // 合并预设
      const allPresets = [...serverPresetList, ...localPresets];
      setPresets(allPresets);
    } catch (error) {
      console.error('加载预设失败:', error);
      // 失败时设置为空数组而不是保持原状态
      setPresets([]);
    }
  };

  const savePresets = (newPresets: ParameterPreset[]) => {
    // 只保存本地预设到 localStorage
    const localOnly = newPresets.filter(p => !p.id.startsWith('server_'));
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(localOnly));
    setPresets(newPresets);
  };

  const handleSavePreset = () => {
    const currentParams = form.getFieldValue('parameters');
    if (!presetName.trim()) {
      message.error('请输入预设名称');
      return;
    }

    const newPreset: ParameterPreset = {
      id: Date.now().toString(),
      name: presetName.trim(),
      description: presetDesc.trim(),
      parameters: currentParams,
      created_at: new Date().toISOString(),
    };

    savePresets([...presets, newPreset]);
    setPresetModalVisible(false);
    setPresetName('');
    setPresetDesc('');
    message.success('预设保存成功');
  };

  const handleLoadPreset = (preset: ParameterPreset) => {
    form.setFieldsValue({ parameters: preset.parameters });
    setSelectedPresetId(preset.id);
    message.success(`已加载预设: ${preset.name}`);
  };

  const handleDeletePreset = (id: string) => {
    // 只能删除本地预设（id 不以 'server_' 开头）
    if (id.startsWith('server_')) {
      message.warning('服务端预设不可删除');
      return;
    }

    // 从本地存储中删除
    const stored = localStorage.getItem(PRESET_STORAGE_KEY);
    const localPresets: ParameterPreset[] = stored ? JSON.parse(stored) : [];
    const updatedLocalPresets = localPresets.filter(p => p.id !== id);
    localStorage.setItem(PRESET_STORAGE_KEY, JSON.stringify(updatedLocalPresets));

    // 更新当前显示的预设列表（保留服务端预设）
    setPresets(prev => prev.filter(p => p.id !== id));

    if (selectedPresetId === id) {
      setSelectedPresetId(null);
    }
    message.success('预设已删除');
  };

  const runBacktest = async (values: any) => {
    setLoading(true);
    try {
      const response = await backtestApi.runBacktest({
        parameters: values.parameters,
        start_date: values.start_date,
        end_date: values.end_date,
        interval: values.interval,
        initial_capital: values.initial_capital,
        position_size: values.position_size,
        use_tick_backtest: values.use_tick_backtest ?? true,
      });
      setResult(response);
      if (response.success) {
        if (response.data_info?.warning) {
          message.warning(response.data_info.warning);
        } else {
          message.success('回测完成');
        }
      } else {
        message.error(response.error || '回测失败');
      }
    } catch (error: any) {
      message.error(error.message || '回测请求失败');
    } finally {
      setLoading(false);
    }
  };

  const resetForm = () => {
    if (config) {
      form.setFieldsValue({
        parameters: config.default_params,
        start_date: '2025-08-01',
        end_date: '2026-02-28',
        interval: '15m',
        initial_capital: 100000,
        position_size: 1.0,
        use_tick_backtest: true,
      });
    }
    setResult(null);
    setSelectedPresetId(null);
  };

  const getEquityChartOption = () => {
    if (!result?.equity_curve) return {};

    const data = result.equity_curve.map((point) => [
      point.timestamp,
      point.equity,
    ]);

    return {
      title: {
        text: '权益曲线',
        left: 'center',
      },
      tooltip: {
        trigger: 'axis',
        formatter: (params: any) => {
          const point = params[0];
          return `${point.axisValue}<br/>权益: $${point.value[1].toLocaleString()}`;
        },
      },
      xAxis: {
        type: 'time',
        splitLine: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          formatter: (value: number) => `$${(value / 1000).toFixed(0)}K`,
        },
      },
      series: [
        {
          type: 'line',
          data: data,
          smooth: true,
          lineStyle: { width: 2 },
          areaStyle: {
            color: {
              type: 'linear',
              x: 0,
              y: 0,
              x2: 0,
              y2: 1,
              colorStops: [
                { offset: 0, color: 'rgba(24, 144, 255, 0.3)' },
                { offset: 1, color: 'rgba(24, 144, 255, 0.05)' },
              ],
            },
          },
        },
      ],
      grid: {
        left: '10%',
        right: '10%',
        bottom: '15%',
      },
      dataZoom: [
        { type: 'inside', start: 0, end: 100 },
        { type: 'slider', start: 0, end: 100 },
      ],
    };
  };

  const tradeColumns = [
    {
      title: '入场时间',
      dataIndex: 'entry_time',
      key: 'entry_time',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '出场时间',
      dataIndex: 'exit_time',
      key: 'exit_time',
      width: 160,
      render: (v: string) => v ? new Date(v).toLocaleString('zh-CN') : '-',
    },
    {
      title: '方向',
      dataIndex: 'direction',
      key: 'direction',
      width: 80,
      render: (v: string) => (
        <span style={{ color: v === 'LONG' ? '#52c41a' : '#ff4d4f' }}>
          {v === 'LONG' ? '做多' : '做空'}
        </span>
      ),
    },
    {
      title: '策略',
      dataIndex: 'strategy',
      key: 'strategy',
      width: 80,
      render: (v: string) => `策略${v}`,
    },
    {
      title: '入场价',
      dataIndex: 'entry_price',
      key: 'entry_price',
      width: 100,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '出场价',
      dataIndex: 'exit_price',
      key: 'exit_price',
      width: 100,
      render: (v: number) => v.toFixed(2),
    },
    {
      title: '盈亏($)',
      dataIndex: 'pnl',
      key: 'pnl',
      width: 100,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f', fontWeight: 'bold' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}
        </span>
      ),
    },
    {
      title: '盈亏%',
      dataIndex: 'pnl_pct',
      key: 'pnl_pct',
      width: 80,
      render: (v: number) => (
        <span style={{ color: v >= 0 ? '#52c41a' : '#ff4d4f' }}>
          {v >= 0 ? '+' : ''}{v.toFixed(2)}%
        </span>
      ),
    },
    {
      title: '出场原因',
      dataIndex: 'exit_reason',
      key: 'exit_reason',
      ellipsis: true,
    },
  ];

  const renderStatsCards = (stats: BacktestResult) => (
    <Row gutter={[16, 16]}>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总收益率"
            value={stats.total_return}
            precision={2}
            suffix="%"
            valueStyle={{ color: stats.total_return >= 0 ? '#52c41a' : '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总交易次数"
            value={stats.total_trades}
            suffix={`次 (胜率 ${stats.win_rate.toFixed(1)}%)`}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="最大回撤"
            value={stats.max_drawdown}
            precision={2}
            suffix="%"
            valueStyle={{ color: '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic title="夏普比率" value={stats.sharpe_ratio} precision={2} />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="总盈亏"
            value={stats.total_pnl}
            precision={2}
            prefix="$"
            valueStyle={{ color: stats.total_pnl >= 0 ? '#52c41a' : '#ff4d4f' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic title="盈亏比" value={stats.profit_factor} precision={2} />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="最大盈利"
            value={stats.max_win}
            precision={2}
            prefix="$"
            valueStyle={{ color: '#52c41a' }}
          />
        </Card>
      </Col>
      <Col xs={12} md={6}>
        <Card size="small" className="stat-card">
          <Statistic
            title="最大亏损"
            value={stats.max_loss}
            precision={2}
            prefix="$"
            valueStyle={{ color: '#ff4d4f' }}
          />
        </Card>
      </Col>
    </Row>
  );

  // 参数分组
  const commonParams = ['bb_period', 'bb_std', 'kc_period', 'kc_atr_mult', 'atr_period', 'rsi_period'];
  const strategyAParams = ['rsi_oversold', 'rsi_overbought', 'stop_loss_atr_mult_a', 'max_hold_bars_a'];
  const strategyBParams = ['ema_fast', 'ema_slow', 'stop_loss_atr_mult_b', 'trailing_stop_atr_mult', 'squeeze_threshold'];
  const advancedParams = ['atr_time_stop_base', 'atr_time_stop_mult', 'volatility_filter_period', 'volatility_filter_mult', 'pullback_confirmation_bars', 'ema_momentum_threshold'];

  // 参数中文映射
  const paramNames: Record<string, string> = {
    // 通用参数
    bb_period: '布林带周期',
    bb_std: '布林带标准差',
    kc_period: '肯特纳周期',
    kc_atr_mult: '肯特纳ATR倍数',
    atr_period: 'ATR周期',
    rsi_period: 'RSI周期',
    // 策略A参数
    rsi_oversold: 'RSI超卖阈值',
    rsi_overbought: 'RSI超买阈值',
    stop_loss_atr_mult_a: '止损ATR倍数(A)',
    max_hold_bars_a: '最大持仓K线(A)',
    // 策略B参数
    ema_fast: '快速EMA',
    ema_slow: '慢速EMA',
    stop_loss_atr_mult_b: '止损ATR倍数(B)',
    trailing_stop_atr_mult: '追踪止损ATR倍数',
    squeeze_threshold: '挤压阈值',
    // 高级参数
    atr_time_stop_base: 'ATR时间止损基础',
    atr_time_stop_mult: 'ATR时间止损倍数',
    volatility_filter_period: '波动率过滤周期',
    volatility_filter_mult: '波动率过滤倍数',
    pullback_confirmation_bars: '回踩确认K线',
    ema_momentum_threshold: 'EMA动能阈值',
  };

  const renderParamInput = (key: string) => (
    <Col xs={12} md={6} key={key}>
      <Form.Item name={['parameters', key]} label={paramNames[key] || key}>
        <InputNumber style={{ width: '100%' }} />
      </Form.Item>
    </Col>
  );

  return (
    <div style={{ maxWidth: 1400, margin: '0 auto' }}>
      {/* 回测设置 */}
      <Card
        title={
          <Space>
            <SettingOutlined />
            回测设置
          </Space>
        }
        extra={
          <Space>
            <Dropdown
              menu={{
                items: presets.length === 0
                  ? [{ key: 'empty', label: '加载中...' }]
                  : presets.map(p => ({
                      key: p.id,
                      label: (
                        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                          <span>{p.name}</span>
                          {/* 只有本地预设才显示删除按钮 */}
                          {!p.id.startsWith('server_') && (
                            <Button
                              type="text"
                              size="small"
                              danger
                              icon={<DeleteOutlined />}
                              onClick={(e) => {
                                e.stopPropagation();
                                handleDeletePreset(p.id);
                              }}
                            />
                          )}
                        </div>
                      ),
                    })),
                onClick: ({ key }) => {
                  const preset = presets.find(p => p.id === key);
                  if (preset) handleLoadPreset(preset);
                },
              }}
            >
              <Button icon={<FolderOutlined />}>
                加载预设{presets.length > 0 ? ` (${presets.length})` : ''}
              </Button>
            </Dropdown>
            <Button
              icon={<SaveOutlined />}
              onClick={() => setPresetModalVisible(true)}
            >
              保存预设
            </Button>
          </Space>
        }
        style={{ marginBottom: 24 }}
      >
        <Form form={form} layout="vertical" onFinish={runBacktest}>
          {/* 基本设置 */}
          <Row gutter={16}>
            <Col xs={12} md={3}>
              <Form.Item name="start_date" label="开始日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="end_date" label="结束日期">
                <Input placeholder="YYYY-MM-DD" style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="interval" label="数据周期">
                <Select
                  options={(config?.intervals || ['15m', '30m', '1h', '1d']).map(i => ({
                    value: i,
                    label: i,
                  }))}
                />
              </Form.Item>
            </Col>
            <Col xs={12} md={4}>
              <Form.Item name="initial_capital" label="初始资金">
                <InputNumber min={10000} step={10000} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="position_size" label="持仓手数">
                <InputNumber min={0.1} max={10} step={0.1} style={{ width: '100%' }} />
              </Form.Item>
            </Col>
            <Col xs={12} md={3}>
              <Form.Item name="use_tick_backtest" label="Tick级回测" valuePropName="checked">
                <Checkbox>启用</Checkbox>
              </Form.Item>
            </Col>
            <Col xs={24} md={6}>
              <Form.Item label=" ">
                <Space>
                  <Button type="primary" htmlType="submit" icon={<PlayCircleOutlined />} loading={loading}>
                    运行回测
                  </Button>
                  <Button icon={<ReloadOutlined />} onClick={resetForm}>
                    重置
                  </Button>
                </Space>
              </Form.Item>
            </Col>
          </Row>

          <Divider style={{ margin: '12px 0' }} />

          {/* 所有参数在一个页面 */}
          <Card size="small" title="通用参数" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              {commonParams.map(renderParamInput)}
            </Row>
          </Card>

          <Row gutter={16}>
            <Col xs={24} md={12}>
              <Card size="small" title="策略A (均值回归)" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                  {strategyAParams.map(renderParamInput)}
                </Row>
              </Card>
            </Col>
            <Col xs={24} md={12}>
              <Card size="small" title="策略B (动量突破)" style={{ marginBottom: 16 }}>
                <Row gutter={16}>
                  {strategyBParams.map(renderParamInput)}
                </Row>
              </Card>
            </Col>
          </Row>

          <Card size="small" title="高级参数 (Module 1 & 2)" style={{ marginBottom: 16 }}>
            <Row gutter={16}>
              {advancedParams.map(renderParamInput)}
            </Row>
          </Card>
        </Form>
      </Card>

      {/* 数据警告 */}
      {result?.data_info?.warning && (
        <Alert
          message={result.data_info.warning}
          type="warning"
          showIcon
          style={{ marginBottom: 24 }}
        />
      )}

      {/* 加载中 */}
      {loading && (
        <Card style={{ textAlign: 'center', padding: 40 }}>
          <Spin size="large" tip="正在运行回测..." />
        </Card>
      )}

      {/* 回测结果 */}
      {result?.success && result.result && (
        <>
          <Card title="回测结果" style={{ marginBottom: 24 }}>
            {renderStatsCards(result.result)}
          </Card>

          <Card title="权益曲线" style={{ marginBottom: 24 }}>
            <ReactECharts option={getEquityChartOption()} style={{ height: 400 }} notMerge />
          </Card>

          <Card title="交易记录">
            <Table
              className="trade-table"
              dataSource={result.trades || []}
              columns={tradeColumns}
              rowKey={(record) => record.entry_time + record.strategy}
              scroll={{ x: 1000 }}
              pagination={{ pageSize: 20 }}
              size="small"
            />
          </Card>
        </>
      )}

      {/* 保存预设弹窗 */}
      <Modal
        title="保存参数预设"
        open={presetModalVisible}
        onOk={handleSavePreset}
        onCancel={() => setPresetModalVisible(false)}
        okText="保存"
        cancelText="取消"
      >
        <Form layout="vertical">
          <Form.Item label="预设名称" required>
            <Input
              value={presetName}
              onChange={(e) => setPresetName(e.target.value)}
              placeholder="例如: 保守型策略"
            />
          </Form.Item>
          <Form.Item label="描述">
            <Input.TextArea
              value={presetDesc}
              onChange={(e) => setPresetDesc(e.target.value)}
              placeholder="可选：描述这个参数组合的特点"
              rows={2}
            />
          </Form.Item>
        </Form>
      </Modal>
    </div>
  );
};

export default BacktestPage;
