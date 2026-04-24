"""
通知模块：支持微信企业号、钉钉机器人、Server酱等多渠道推送

使用方式：
    from notifier import Notifier
    
    n = Notifier()
    n.send("买入信号", "510300 触发金叉，建议买入价 4.05")

配置方式（环境变量）：
    WECHAT_CORP_ID=企业微信CorpID
    WECHAT_AGENT_ID=应用AgentID
    WECHAT_SECRET=应用Secret
    WECHAT_TO_USER=@all
    
    DINGTALK_WEBHOOK=钉钉机器人Webhook地址
    DINGTALK_SECRET=钉钉机器人加签密钥
    
    SERVERCHAN_KEY=Server酱SendKey
"""

import os
import json
import time
import hmac
import hashlib
import base64
import urllib.parse
import requests
from datetime import datetime
from typing import Optional


class Notifier:
    """
    多渠道通知器
    
    优先级：微信企业号 > 钉钉 > Server酱 > 控制台打印
    至少配置一个渠道即可收到通知
    """
    
    def __init__(self):
        # 微信企业号配置
        self.wx_corp_id = os.getenv("WECHAT_CORP_ID", "")
        self.wx_agent_id = os.getenv("WECHAT_AGENT_ID", "")
        self.wx_secret = os.getenv("WECHAT_SECRET", "")
        self.wx_to_user = os.getenv("WECHAT_TO_USER", "@all")
        self._wx_access_token = None
        self._wx_token_expire = 0
        
        # 钉钉配置
        self.ding_webhook = os.getenv("DINGTALK_WEBHOOK", "")
        self.ding_secret = os.getenv("DINGTALK_SECRET", "")
        
        # Server酱配置
        self.serverchan_key = os.getenv("SERVERCHAN_KEY", "")
        
        # 飞书配置
        self.feishu_webhook = os.getenv("FEISHU_WEBHOOK", "")
        
        # 记录哪些渠道可用
        self.channels = []
        if self.feishu_webhook:
            self.channels.append("feishu")
        if self.wx_corp_id and self.wx_secret:
            self.channels.append("wechat")
        if self.ding_webhook:
            self.channels.append("dingtalk")
        if self.serverchan_key:
            self.channels.append("serverchan")
        
        if not self.channels:
            print("⚠️ 未配置任何通知渠道，将只打印到控制台")
        else:
            print(f"✅ 已启用通知渠道: {', '.join(self.channels)}")
    
    # ==================== 微信企业号 ====================
    
    def _get_wx_access_token(self) -> str:
        """获取企业微信 access_token（带缓存）"""
        if self._wx_access_token and time.time() < self._wx_token_expire:
            return self._wx_access_token
        
        url = (
            f"https://qyapi.weixin.qq.com/cgi-bin/gettoken"
            f"?corpid={self.wx_corp_id}&corpsecret={self.wx_secret}"
        )
        resp = requests.get(url, timeout=10)
        data = resp.json()
        
        if data.get("errcode") != 0:
            raise RuntimeError(f"获取微信token失败: {data}")
        
        self._wx_access_token = data["access_token"]
        self._wx_token_expire = time.time() + 7000  # token 有效期 7200 秒，提前 200 秒刷新
        return self._wx_access_token
    
    def _send_wechat(self, title: str, content: str) -> bool:
        """通过微信企业号发送消息"""
        try:
            token = self._get_wx_access_token()
            url = f"https://qyapi.weixin.qq.com/cgi-bin/message/send?access_token={token}"
            
            # 构建消息内容
            full_content = f"{title}\n\n{content}"
            
            payload = {
                "touser": self.wx_to_user,
                "msgtype": "text",
                "agentid": self.wx_agent_id,
                "text": {"content": full_content},
                "safe": 0
            }
            
            resp = requests.post(url, json=payload, timeout=10)
            data = resp.json()
            
            if data.get("errcode") == 0:
                print("✅ 微信通知发送成功")
                return True
            else:
                print(f"❌ 微信通知失败: {data}")
                return False
        except Exception as e:
            print(f"❌ 微信通知异常: {e}")
            return False
    
    # ==================== 钉钉机器人 ====================
    
    def _send_dingtalk(self, title: str, content: str) -> bool:
        """通过钉钉机器人发送消息"""
        try:
            timestamp = str(round(time.time() * 1000))
            
            # 加签
            if self.ding_secret:
                secret_enc = self.ding_secret.encode("utf-8")
                string_to_sign = f"{timestamp}\n{self.ding_secret}".encode("utf-8")
                hmac_code = hmac.new(secret_enc, string_to_sign, digestmod=hashlib.sha256).digest()
                sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
                webhook = f"{self.ding_webhook}&timestamp={timestamp}&sign={sign}"
            else:
                webhook = self.ding_webhook
            
            payload = {
                "msgtype": "markdown",
                "markdown": {
                    "title": title,
                    "text": f"### {title}\n\n{content}"
                }
            }
            
            resp = requests.post(webhook, json=payload, timeout=10)
            data = resp.json()
            
            if data.get("errcode") == 0:
                print("✅ 钉钉通知发送成功")
                return True
            else:
                print(f"❌ 钉钉通知失败: {data}")
                return False
        except Exception as e:
            print(f"❌ 钉钉通知异常: {e}")
            return False
    
    # ==================== 飞书机器人 ====================

    def _send_feishu(self, title: str, content: str) -> bool:
        """通过飞书机器人发送消息"""
        try:
            payload = {
                "msg_type": "text",
                "content": {
                    "text": f"{title}\n\n{content}"
                }
            }
            resp = requests.post(self.feishu_webhook, json=payload, timeout=10)
            data = resp.json()
            if data.get("code") == 0:
                print("✅ 飞书通知发送成功")
                return True
            else:
                print(f"❌ 飞书通知失败: {data}")
                return False
        except Exception as e:
            print(f"❌ 飞书通知异常: {e}")
            return False

    # ==================== Server酱 ====================
    
    def _send_serverchan(self, title: str, content: str) -> bool:
        """通过 Server酱 发送消息"""
        try:
            url = f"https://sctapi.ftqq.com/{self.serverchan_key}.send"
            payload = {"title": title, "desp": content}
            
            resp = requests.post(url, data=payload, timeout=10)
            data = resp.json()
            
            if data.get("code") == 0 or data.get("data", {}).get("errno") == 0:
                print("✅ Server酱通知发送成功")
                return True
            else:
                print(f"❌ Server酱通知失败: {data}")
                return False
        except Exception as e:
            print(f"❌ Server酱通知异常: {e}")
            return False
    
    # ==================== 统一入口 ====================
    
    def send(self, title: str, content: str) -> dict:
        """
        发送通知到所有已配置的渠道
        
        Args:
            title: 消息标题
            content: 消息正文
            
        Returns:
            dict: 各渠道发送结果
        """
        print(f"\n📢 [{title}]")
        print(content)
        print("-" * 40)
        
        results = {}
        
        if "feishu" in self.channels:
            results["feishu"] = self._send_feishu(title, content)
        
        if "wechat" in self.channels:
            results["wechat"] = self._send_wechat(title, content)
        
        if "dingtalk" in self.channels:
            results["dingtalk"] = self._send_dingtalk(title, content)
        
        if "serverchan" in self.channels:
            results["serverchan"] = self._send_serverchan(title, content)
        
        if not self.channels:
            results["console"] = True
        
        return results
    
    def send_trade_signal(self, signal_type: str, code: str, name: str,
                          price: float, ma_values: dict = None,
                          extra_info: str = "") -> dict:
        """
        发送交易信号通知（格式化模板）
        
        Args:
            signal_type: "买入" / "卖出" / "止损"
            code: ETF代码
            name: ETF名称
            price: 当前价格/建议价格
            ma_values: 均线数值字典
            extra_info: 额外信息
        """
        emoji = {"买入": "📈", "卖出": "📉", "止损": "🛑"}.get(signal_type, "📊")
        title = f"{emoji} ETF交易信号 — {signal_type}"
        
        content_lines = [
            f"**标的**: {name} ({code})",
            f"**信号**: {signal_type}",
            f"**参考价格**: {price:.3f} 元",
        ]
        
        if ma_values:
            for k, v in ma_values.items():
                content_lines.append(f"**{k.upper()}**: {v:.3f}")
        
        if extra_info:
            content_lines.append(f"\n{extra_info}")
        
        content_lines.append("\n⏰ 请在券商APP中手动操作")
        content_lines.append(f"\n⏱️ 通知时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        
        content = "\n".join(content_lines)
        return self.send(title, content)
    
    def send_daily_report(self, report: dict) -> dict:
        """
        发送每日策略运行报告（单只 ETF，兼容旧接口）
        
        Args:
            report: 回测/信号报告字典
        """
        return self.send_daily_summary([report], report.get("strategy", "hybrid"))
    
    def send_daily_summary(self, reports: list, strategy: str = "hybrid") -> dict:
        """
        发送每日多 ETF 汇总报告
        
        Args:
            reports: ETF 报告列表，每个元素为 dict
            strategy: 策略名称
        """
        title = f"📊 ETF每日报告 ({len(reports)}只)"
        
        content_lines = [
            f"**报告日期**: {reports[0].get('time', 'N/A')}",
            f"**策略**: {strategy}",
            f"**监控标的**: {len(reports)} 只 ETF",
            "",
            "---",
        ]
        
        for i, r in enumerate(reports, 1):
            content_lines.append(f"\n**{i}. {r['name']} ({r['code']})**")
            content_lines.append(f"收盘价: {r['close']:.3f} | 信号: {r['signal_label']}")
            
            if r.get("ma_values"):
                ma_str = " | ".join([f"{k.upper()}={v:.3f}" for k, v in r["ma_values"].items()])
                content_lines.append(ma_str)
            
            if r.get("action"):
                content_lines.append(f"💡 {r['action']}")
        
        content_lines.append("\n---")
        content_lines.append(f"\n⏰ 报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        content_lines.append("以上建议仅供参考，投资有风险")
        
        content = "\n".join(content_lines)
        return self.send(title, content)


# ==================== 测试入口 ====================

if __name__ == "__main__":
    n = Notifier()
    
    # 测试交易信号
    n.send_trade_signal(
        signal_type="买入",
        code="510300",
        name="华泰柏瑞沪深300ETF",
        price=4.052,
        ma_values={"ma5": 4.010, "ma20": 3.998, "ma60": 3.950},
        extra_info="MA5上穿MA20，趋势向上，建议建仓"
    )
