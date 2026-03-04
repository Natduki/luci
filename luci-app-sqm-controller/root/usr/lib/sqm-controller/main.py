#!/usr/bin/env python3
"""
SQM控制器主程序
OpenWrt流量控制管理
"""
import argparse
import sys
import logging
from config_manager import ConfigManager
from tc_manager import TCManager
class SQMController:
    """SQM控制器主类"""
    
    def __init__(self, config_path=None):
        """初始化控制器"""
        self.config_manager = ConfigManager(config_path)
        self.config = self.config_manager.get_settings()
        self.logger = self._setup_logging()
        
    def _setup_logging(self):
        """设置日志"""
        log_level = logging.INFO
        if self.config.get('debug', False):
            log_level = logging.DEBUG
        
        logging.basicConfig(
            level=log_level,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        return logging.getLogger(__name__)
    
    def enable(self, interface=None):
        """启用流量控制"""
        try:
            if interface:
                self.config['interface'] = interface
            
            self.logger.info(f"启用流量控制: 接口={self.config['interface']}")
            
            # 创建TC管理器
            tc_manager = TCManager(self.config)
            
            # 设置HTB队列
            success = tc_manager.setup_htb()
            
            if success:
                self.logger.info("流量控制启用成功")
                
                # 更新配置状态
                self.config_manager.set_value('enabled', True)
                if interface:
                    self.config_manager.set_value('interface', interface)
                self.config_manager.save_config()
                
                return True
            else:
                self.logger.error("流量控制启用失败")
                return False
                
        except Exception as e:
            self.logger.error(f"启用流量控制时发生错误: {e}")
            return False
    
    def disable(self, interface=None):
        """禁用流量控制"""
        try:
            if interface:
                self.config['interface'] = interface
            
            self.logger.info(f"禁用流量控制: 接口={self.config['interface']}")
            
            # 创建TC管理器
            tc_manager = TCManager(self.config)
            
            # 清除TC规则
            tc_manager.clear_tc_rules()
            
            self.logger.info("流量控制已禁用")
            
            # 更新配置状态
            self.config_manager.set_value('enabled', False)
            if interface:
                self.config_manager.set_value('interface', interface)
            self.config_manager.save_config()
            
            return True
            
        except Exception as e:
            self.logger.error(f"禁用流量控制时发生错误: {e}")
            return False
    
    def status(self):
        """显示状态"""
        try:
            # 创建TC管理器
            tc_manager = TCManager(self.config)
            
            # 获取当前带宽
            current_bw = tc_manager.get_current_bandwidth()
            
            print("SQM流量控制状态")
            print("===================")
            print(f"配置文件: {self.config_manager.config_path}")
            print(f"网络接口: {self.config.get('interface', '未设置')}")
            print(f"启用状态: {self.config.get('enabled', False)}")
            print(f"配置带宽: 上传={self.config.get('upload_bandwidth', 0)}kbps, "
                  f"下载={self.config.get('download_bandwidth', 0)}kbps")
            print(f"当前带宽: 上传={current_bw['upload']}kbps, 下载={current_bw['download']}kbps")
            
            # 检查TC规则
            tc_status = tc_manager.show_status()
            if tc_status:
                print("\nTC规则状态:")
                for cmd, output in tc_status.items():
                    if output and output.strip():
                        print(f"\n--- {cmd.split()[0]} ---")
                        print(output.strip()[:500])  # 限制输出长度
            else:
                print("\n未检测到TC规则")
                
        except Exception as e:
            print(f"获取状态时发生错误: {e}")
    
    def test(self, interface=None):
        """测试模式（不实际应用规则）"""
        try:
            if interface:
                self.config['interface'] = interface
            
            print("测试模式 - 将显示要执行的命令但不实际执行")
            print("=========================================")
            print(f"配置文件: {self.config_manager.config_path}")
            print(f"网络接口: {self.config.get('interface', '未设置')}")
            print(f"上传带宽: {self.config.get('upload_bandwidth', 0)}kbps")
            print(f"下载带宽: {self.config.get('download_bandwidth', 0)}kbps")
            print(f"队列算法: {self.config.get('algorithm', 'fq_codel')}")
            print()
            
            # 创建TC管理器
            tc_manager = TCManager(self.config)
            
            print("上传方向命令:")
            print("-" * 50)
            upload_commands = tc_manager.generate_commands('upload')
            for i, cmd in enumerate(upload_commands, 1):
                print(f"{i:2}. {cmd}")
            
            print("\n下载方向命令:")
            print("-" * 50)
            download_commands = tc_manager.generate_commands('download')
            for i, cmd in enumerate(download_commands, 1):
                print(f"{i:2}. {cmd}")
            
            print(f"\n总计 {len(upload_commands) + len(download_commands)} 条命令")
            print("\n注意：这些命令仅显示，不会实际执行")
            print("使用 --enable 参数实际应用这些规则")
            
        except Exception as e:
            print(f"测试模式时发生错误: {e}")
            import traceback
            traceback.print_exc()
def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="SQM控制器 - OpenWrt流量控制管理",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  %(prog)s --status                  # 显示当前状态
  %(prog)s --enable --interface eth0 # 启用流量控制
  %(prog)s --disable                 # 禁用流量控制
  %(prog)s --test --interface eth0   # 测试模式
        """
    )
    
    parser.add_argument("--config", help="配置文件路径")
    parser.add_argument("--interface", help="网络接口名称")
    parser.add_argument("--enable", action="store_true", help="启用流量控制")
    parser.add_argument("--disable", action="store_true", help="禁用流量控制")
    parser.add_argument("--status", action="store_true", help="显示当前状态")
    parser.add_argument("--test", action="store_true", help="测试模式（不实际应用规则）")
    parser.add_argument("--debug", action="store_true", help="调试模式")
    
    args = parser.parse_args()
    
    # 如果没有指定任何操作，显示帮助
    if not (args.enable or args.disable or args.status or args.test):
        parser.print_help()
        
        # 显示当前配置信息
        try:
            controller = SQMController(args.config)
            print("\n当前配置:")
            print(f"  配置文件: {controller.config_manager.config_path}")
            print(f"  网络接口: {controller.config.get('interface', '未设置')}")
            print(f"  启用状态: {controller.config.get('enabled', False)}")
        except:
            pass
        
        return
    
    # 创建控制器
    controller = SQMController(args.config)
    
    # 设置调试模式
    if args.debug:
        controller.config['debug'] = True
        controller.logger.setLevel(logging.DEBUG)
    
    # 执行操作
    if args.status:
        controller.status()
    elif args.test:
        controller.test(args.interface)
    elif args.enable:
        if controller.enable(args.interface):
            print("✅ 流量控制已启用")
        else:
            print("❌ 流量控制启用失败")
            sys.exit(1)
    elif args.disable:
        if controller.disable(args.interface):
            print("✅ 流量控制已禁用")
        else:
            print("❌ 流量控制禁用失败")
            sys.exit(1)
if __name__ == "__main__":
    main()