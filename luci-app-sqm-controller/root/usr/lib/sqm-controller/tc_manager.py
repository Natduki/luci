#!/usr/bin/env python3
"""
流量控制管理器
使用Linux TC命令管理队列规则
"""
import subprocess
import logging
import json
class TCManager:
    """流量控制管理器"""
    
    def __init__(self, config):
        """
        初始化流量控制管理器
        
        Args:
            config: 配置字典，包含带宽和接口信息
        """
        if isinstance(config, str):
            # 如果传入的是接口名（兼容旧版本）
            self.interface = config
            self.upload_kbps = 50000  # 默认值
            self.download_kbps = 100000  # 默认值
        elif isinstance(config, dict):
            # 如果传入的是配置字典
            self.interface = config.get('interface', 'eth0')
            
            # 支持多种带宽字段名
            if 'upload_speed' in config:
                self.upload_kbps = int(config['upload_speed'])
            elif 'upload_bandwidth' in config:
                self.upload_kbps = int(config['upload_bandwidth'])
            else:
                self.upload_kbps = 50000
                
            if 'download_speed' in config:
                self.download_kbps = int(config['download_speed'])
            elif 'download_bandwidth' in config:
                self.download_kbps = int(config['download_bandwidth'])
            else:
                self.download_kbps = 100000
        else:
            raise ValueError("config参数必须是字符串（接口名）或字典（配置）")
        
        self.algorithm = config.get('algorithm', 'fq_codel') if isinstance(config, dict) else 'fq_codel'
        self.logger = logging.getLogger(__name__)
    
    def run_command(self, cmd):
        """执行Shell命令"""
        self.logger.debug(f"执行命令: {cmd}")
        try:
            result = subprocess.run(
                cmd, 
                shell=True, 
                capture_output=True, 
                text=True,
                timeout=10
            )
            if result.returncode != 0:
                self.logger.warning(f"命令执行失败: {cmd}")
                self.logger.warning(f"错误: {result.stderr}")
            return result
        except subprocess.TimeoutExpired:
            self.logger.error(f"命令执行超时: {cmd}")
            return None
        except Exception as e:
            self.logger.error(f"命令执行异常: {cmd}, 错误: {e}")
            return None
    
    def clear_tc_rules(self):
        """清除所有TC规则"""
        commands = [
            f"tc qdisc del dev {self.interface} root 2>/dev/null || true",
            f"tc qdisc del dev {self.interface} ingress 2>/dev/null || true",
            f"tc qdisc del dev ifb0 root 2>/dev/null || true",
            f"ip link set dev ifb0 down 2>/dev/null || true"
        ]
        
        for cmd in commands:
            self.run_command(cmd)
        
        return True
    
    def setup_htb(self):
        """
        设置HTB队列规则
        """
        self.logger.info(f"设置HTB队列规则: 接口={self.interface}, 上传={self.upload_kbps}kbps, 下载={self.download_kbps}kbps")
        
        # 清除现有规则
        self.clear_tc_rules()
        
        # 生成命令序列
        commands = []
        
        # 设置上传方向 (egress)
        if self.upload_kbps > 0:
            commands.extend([
                f"tc qdisc add dev {self.interface} root handle 1: htb default 10",
                f"tc class add dev {self.interface} parent 1: classid 1:1 htb rate {self.upload_kbps}kbit",
                f"tc class add dev {self.interface} parent 1:1 classid 1:10 htb rate {self.upload_kbps}kbit",
                f"tc qdisc add dev {self.interface} parent 1:10 handle 10: {self.algorithm}"
            ])
        
        # 设置下载方向 (ingress, 需要ifb虚拟接口)
        if self.download_kbps > 0:
            commands.extend([
                f"modprobe ifb numifbs=1 2>/dev/null || true",
                f"ip link set dev ifb0 up 2>/dev/null || true",
                f"tc qdisc add dev {self.interface} ingress",
                f"tc filter add dev {self.interface} parent ffff: protocol ip u32 match u32 0 0 flowid 1:1 action mirred egress redirect dev ifb0",
                f"tc qdisc add dev ifb0 root handle 2: htb default 20",
                f"tc class add dev ifb0 parent 2: classid 2:1 htb rate {self.download_kbps}kbit",
                f"tc class add dev ifb0 parent 2:1 classid 2:20 htb rate {self.download_kbps}kbit",
                f"tc qdisc add dev ifb0 parent 2:20 handle 20: {self.algorithm}"
            ])
        
        # 执行命令
        success_count = 0
        for cmd in commands:
            result = self.run_command(cmd)
            if result and result.returncode == 0:
                success_count += 1
            else:
                self.logger.error(f"命令执行失败: {cmd}")
        
        return success_count == len(commands)
    
    def generate_commands(self, direction='download'):
        """
        生成TC命令（用于测试模式）
        
        Args:
            direction: 'download' 或 'upload'
        
        Returns:
            命令列表
        """
        commands = []
        
        if direction == 'upload' and self.upload_kbps > 0:
            commands = [
                f"# 上传方向 (egress) - 接口: {self.interface}",
                f"tc qdisc add dev {self.interface} root handle 1: htb default 10",
                f"tc class add dev {self.interface} parent 1: classid 1:1 htb rate {self.upload_kbps}kbit",
                f"tc class add dev {self.interface} parent 1:1 classid 1:10 htb rate {self.upload_kbps}kbit",
                f"tc qdisc add dev {self.interface} parent 1:10 handle 10: {self.algorithm}"
            ]
        elif direction == 'download' and self.download_kbps > 0:
            commands = [
                f"# 下载方向 (ingress) - 接口: {self.interface}",
                f"modprobe ifb numifbs=1",
                f"ip link set dev ifb0 up",
                f"tc qdisc add dev {self.interface} ingress",
                f"tc filter add dev {self.interface} parent ffff: protocol ip u32 match u32 0 0 flowid 1:1 action mirred egress redirect dev ifb0",
                f"tc qdisc add dev ifb0 root handle 2: htb default 20",
                f"tc class add dev ifb0 parent 2: classid 2:1 htb rate {self.download_kbps}kbit",
                f"tc class add dev ifb0 parent 2:1 classid 2:20 htb rate {self.download_kbps}kbit",
                f"tc qdisc add dev ifb0 parent 2:20 handle 20: {self.algorithm}"
            ]
        
        return commands
    
    def show_status(self):
        """显示当前TC状态"""
        status = {}
        
        commands = [
            f"tc -s qdisc show dev {self.interface}",
            f"tc -s class show dev {self.interface}",
            f"ip link show ifb0 2>/dev/null || echo 'ifb0接口不存在'",
            f"tc qdisc show dev ifb0 2>/dev/null || echo 'ifb0无TC规则'"
        ]
        
        for cmd in commands:
            result = self.run_command(cmd)
            if result:
                status[cmd] = result.stdout
        
        return status
    
    def get_current_bandwidth(self):
        """获取当前带宽限制"""
        result = self.run_command(f"tc class show dev {self.interface}")
        bandwidth = {'upload': 0, 'download': 0}
        
        if result and result.stdout:
            # 从tc输出中解析带宽
            for line in result.stdout.split('\n'):
                if 'rate' in line:
                    # 提取带宽值
                    import re
                    match = re.search(r'rate (\d+)kbit', line)
                    if match:
                        bandwidth['upload'] = int(match.group(1))
        
        # 检查ifb0的带宽
        result = self.run_command(f"tc class show dev ifb0 2>/dev/null || echo ''")
        if result and result.stdout:
            for line in result.stdout.split('\n'):
                if 'rate' in line:
                    import re
                    match = re.search(r'rate (\d+)kbit', line)
                    if match:
                        bandwidth['download'] = int(match.group(1))
        
        return bandwidth
if __name__ == "__main__":
    # 测试代码
    import sys
    
    logging.basicConfig(level=logging.INFO)
    
    # 测试不同的配置方式
    print("测试1: 使用接口名创建TCManager")
    tcm1 = TCManager("eth0")
    print(f"接口: {tcm1.interface}, 上传: {tcm1.upload_kbps}kbps, 下载: {tcm1.download_kbps}kbps")
    
    print("\n测试2: 使用配置字典创建TCManager")
    test_config = {
        'interface': 'eth0',
        'upload_bandwidth': 50000,
        'download_bandwidth': 100000,
        'algorithm': 'fq_codel'
    }
    tcm2 = TCManager(test_config)
    print(f"接口: {tcm2.interface}, 上传: {tcm2.upload_kbps}kbps, 下载: {tcm2.download_kbps}kbps")
    
    print("\n测试3: 生成命令")
    print("上传命令:")
    for cmd in tcm2.generate_commands('upload'):
        print(f"  {cmd}")
    
    print("\n下载命令:")
    for cmd in tcm2.generate_commands('download'):
        print(f"  {cmd}")
    
    print("\n测试4: 清除规则（测试）")
    tcm2.clear_tc_rules()
    
    print("\n✅ TCManager测试完成")