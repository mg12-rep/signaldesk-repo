import axios from 'axios';

const BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || 'http://localhost:8000/api/v1';

export const apiClient = {
  // Market Health Header/Gauge
  getMarketHealth: async () => {
    const res = await axios.get(`${BASE_URL}/market-health/`);
    return res.data;
  },

  // Scanner Screen (Minervini & Connors)
  runScanner: async (strategy: 'MINERVINI' | 'CONNORS' | 'ALL' = 'ALL') => {
    const res = await axios.get(`${BASE_URL}/scanner/run`, {
      params: { strategy },
    });
    return res.data;
  },

  // Holdings & Exit Engine Screen
  getHoldings: async (strategy = 'ALL', broker = 'ALL') => {
    const res = await axios.get(`${BASE_URL}/holdings/`, {
      params: { strategy, broker },
    });
    return res.data;
  },

  // Order Execution Modal
  placeOrder: async (orderPayload: {
    broker: string;
    symbol: string;
    exchange?: string;
    order_type?: string;
    quantity: number;
    price?: number;
    stop_loss?: number;
    trailing_stop?: number;
  }) => {
    const res = await axios.post(`${BASE_URL}/orders/place`, orderPayload);
    return res.data;
  },

  // Backtest Screen
  runBacktest: async (payload: {
    symbol: string;
    strategy?: string;
    stop_loss_pct?: number;
    profit_target_pct?: number;
  }) => {
    const res = await axios.post(`${BASE_URL}/backtest/run`, payload);
    return res.data;
  },
};