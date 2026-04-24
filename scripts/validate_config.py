#!/usr/bin/env python3
"""
配置校验脚本 — 飞书多Agent跨实例协作
用法：python validate_config.py

检查项：
1. 配置模板.md 是否存在
2. 必填字段是否已填写（非占位符）
3. ID格式是否正确（ou_/oc_/cli_）
4. 群ID格式是否正确（oc_开头）
5. Bot ID是否有重复
"""

import re
import sys
from pathlib import Path

CONFIG_FILE = Path(__file__).parent.parent / "references" / "配置模板.md"

# 占位符模式（未填写时会看到这些）
PLACEHOLDERS = [
    "ou_你的open_id",
    "oc_你的群ID",
    "cli_你的cli_id",
    "你的群名",
    "你的bot_a名字",
    "你的bot_b名字",
    "你的bot_b_open_id",
    "你的bot_a_open_id",
]

def check_file_exists():
    """检查配置文件是否存在"""
    if not CONFIG_FILE.exists():
        print(f"❌ 错误：配置文件不存在")
        print(f"   路径：{CONFIG_FILE}")
        print(f"   请确保已填写 references/配置模板.md")
        return False
    print(f"✅ 配置文件存在：{CONFIG_FILE}")
    return True

def check_placeholders(content):
    """检查是否有未填写的占位符"""
    found_placeholders = []
    for placeholder in PLACEHOLDERS:
        if placeholder in content:
            found_placeholders.append(placeholder)
    
    if found_placeholders:
        print(f"❌ 错误：发现 {len(found_placeholders)} 个未填写的占位符：")
        for p in found_placeholders[:5]:  # 最多显示5个
            print(f"   - {p}")
        if len(found_placeholders) > 5:
            print(f"   ... 还有 {len(found_placeholders) - 5} 个")
        print(f"\n💡 请打开 {CONFIG_FILE} 替换所有占位符为实际值")
        return False
    print(f"✅ 所有必填字段已填写")
    return True

def check_id_formats(content):
    """检查ID格式是否正确"""
    errors = []
    
    # 检查open_id（ou_开头）
    ou_ids = re.findall(r'open_id[:\s]+["\']?([\w_]+)', content)
    for ou_id in ou_ids:
        if not ou_id.startswith('ou_'):
            errors.append(f"open_id 格式错误：{ou_id}（应以ou_开头）")
        elif ou_id == "ou_你的open_id":
            errors.append(f"open_id 未填写：{ou_id}")
    
    # 检查群ID（oc_开头）
    group_ids = re.findall(r'group_id[:\s]+["\']?([\w_]+)', content)
    for gid in group_ids:
        if not gid.startswith('oc_'):
            errors.append(f"group_id 格式错误：{gid}（应以oc_开头）")
        elif gid == "oc_你的群ID":
            errors.append(f"group_id 未填写：{gid}")
    
    # 检查cli_会话ID（cli_开头）
    cli_ids = re.findall(r'cli_session_id[:\s]+["\']?([\w_]+)', content)
    for cli_id in cli_ids:
        if not cli_id.startswith('cli_'):
            errors.append(f"cli_session_id 格式错误：{cli_id}（应以cli_开头）")
    
    if errors:
        print(f"❌ 发现 {len(errors)} 个ID格式错误：")
        for e in errors:
            print(f"   - {e}")
        return False
    print(f"✅ 所有ID格式正确")
    return True

def check_duplicate_ids(content):
    """检查是否有重复ID（填写时复制粘贴容易出错）"""
    all_ous = re.findall(r'(ou_[\w]+)', content)
    ou_counts = {}
    for ou in all_ous:
        ou_counts[ou] = ou_counts.get(ou, 0) + 1
    
    duplicates = {k: v for k, v in ou_counts.items() if v > 1 and k != "ou_你的open_id"}
    
    if duplicates:
        print(f"⚠️ 警告：发现重复的open_id：")
        for ou, count in duplicates.items():
            print(f"   - {ou} 出现 {count} 次")
        # 不算严重错误，只警告
        return True
    print(f"✅ 无重复ID")
    return True

def main():
    print("=" * 50)
    print("飞书多Agent跨实例协作 — 配置校验")
    print("=" * 50)
    print()
    
    if not check_file_exists():
        sys.exit(1)
    
    content = CONFIG_FILE.read_text(encoding="utf-8")
    
    results = []
    results.append(check_placeholders(content))
    results.append(check_id_formats(content))
    check_duplicate_ids(content)  # 只警告，不强制
    
    print()
    print("=" * 50)
    if all(results):
        print("✅ 配置校验通过！可以启动协作。")
        print()
        print("下一步：")
        print("1. 将配置模板中的内容写入各Bot的MEMORY")
        print("2. 在飞书群里发送测试消息验证通信")
        print("   <at user_id=\"ou_执行者open_id\">执行者名字</at> 通信测试，请回复\"收到\"")
        sys.exit(0)
    else:
        print("❌ 配置校验未通过，请修正上述错误后重新运行。")
        sys.exit(1)

if __name__ == "__main__":
    main()
