"""Generate the reviewed BE-009 university Python course assets."""

# ruff: noqa: E501
# One node per line keeps the 84-node curriculum matrix diffable by reviewers.

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.knowledge_assets import (  # noqa: E402
    CourseAssetBundle,
    generate_asset_schemas,
    validate_course_document,
)

VERSION = "1.0.0"
ID_NAMESPACE = UUID("9c56d2c8-c7a3-4d4b-9ed8-8aeb63ba73b1")
NodeSpec = tuple[str, str, str, str, str, str]
ChapterSpec = tuple[str, str, str, tuple[NodeSpec, ...]]


def stable_id(kind: str, key: str) -> str:
    return str(uuid5(ID_NAMESPACE, f"{kind}:{key}"))


SOURCES: dict[str, tuple[str, str, str, str]] = {
    "interpreter": (
        "Python 教程：使用 Python 解释器",
        "https://docs.python.org/zh-cn/3/tutorial/interpreter.html",
        "Python Software Foundation",
        "解释器、交互模式与脚本执行",
    ),
    "introduction": (
        "Python 教程：Python 速览",
        "https://docs.python.org/zh-cn/3/tutorial/introduction.html",
        "Python Software Foundation",
        "数值、文本、列表与首批程序结构",
    ),
    "stdtypes": (
        "Python 标准库：内置类型",
        "https://docs.python.org/zh-cn/3/library/stdtypes.html",
        "Python Software Foundation",
        "真值、数值、序列、映射与集合语义",
    ),
    "lexical": (
        "Python 语言参考：词法分析",
        "https://docs.python.org/zh-cn/3/reference/lexical_analysis.html",
        "Python Software Foundation",
        "标识符、关键字、字面值与词法结构",
    ),
    "controlflow": (
        "Python 教程：更多流程控制工具",
        "https://docs.python.org/zh-cn/3/tutorial/controlflow.html",
        "Python Software Foundation",
        "分支、循环、函数参数与默认值",
    ),
    "datastructures": (
        "Python 教程：数据结构",
        "https://docs.python.org/zh-cn/3/tutorial/datastructures.html",
        "Python Software Foundation",
        "列表、元组、集合、字典与推导式",
    ),
    "executionmodel": (
        "Python 语言参考：执行模型",
        "https://docs.python.org/zh-cn/3/reference/executionmodel.html",
        "Python Software Foundation",
        "代码块、名称绑定、作用域与异常",
    ),
    "defaults_faq": (
        "Python 编程常见问题：共享默认值",
        "https://docs.python.org/zh-cn/3/faq/programming.html"
        "#why-are-default-values-shared-between-objects",
        "Python Software Foundation",
        "默认值求值时机与可变对象共享陷阱",
    ),
    "modules": (
        "Python 教程：模块",
        "https://docs.python.org/zh-cn/3/tutorial/modules.html",
        "Python Software Foundation",
        "模块、包、导入与脚本入口",
    ),
    "inputoutput": (
        "Python 教程：输入与输出",
        "https://docs.python.org/zh-cn/3/tutorial/inputoutput.html",
        "Python Software Foundation",
        "格式化输出、文件对象与 JSON",
    ),
    "pathlib": (
        "Python 标准库：pathlib",
        "https://docs.python.org/zh-cn/3/library/pathlib.html",
        "Python Software Foundation",
        "面向对象的文件系统路径",
    ),
    "errors": (
        "Python 教程：错误和异常",
        "https://docs.python.org/zh-cn/3/tutorial/errors.html",
        "Python Software Foundation",
        "语法错误、异常处理、抛出与清理",
    ),
    "classes": (
        "Python 教程：类",
        "https://docs.python.org/zh-cn/3/tutorial/classes.html",
        "Python Software Foundation",
        "类、实例、继承、迭代器与生成器",
    ),
    "dataclasses": (
        "PEP 557 — Data Classes",
        "https://peps.python.org/pep-0557/",
        "Python Enhancement Proposals",
        "数据类字段、默认工厂与生成方法",
    ),
    "recursion": (
        "Python 标准库：解释器递归限制",
        "https://docs.python.org/zh-cn/3/library/sys.html#sys.getrecursionlimit",
        "Python Software Foundation",
        "Python 解释器递归深度与调用栈保护",
    ),
    "functional": (
        "Python 函数式编程指引",
        "https://docs.python.org/zh-cn/3/howto/functional.html",
        "Python Software Foundation",
        "迭代器、生成器与惰性数据流",
    ),
    "unittest": (
        "Python 标准库：unittest",
        "https://docs.python.org/zh-cn/3/library/unittest.html",
        "Python Software Foundation",
        "测试用例、断言、夹具与测试发现",
    ),
    "simple_statements": (
        "Python 语言参考：简单语句",
        "https://docs.python.org/zh-cn/3/reference/simple_stmts.html",
        "Python Software Foundation",
        "assert、赋值、return、raise 与导入语义",
    ),
    "venv": (
        "Python 教程：虚拟环境和包",
        "https://docs.python.org/zh-cn/3/tutorial/venv.html",
        "Python Software Foundation",
        "虚拟环境、pip 与依赖隔离",
    ),
    "sqlite3": (
        "Python 标准库：sqlite3",
        "https://docs.python.org/zh-cn/3/library/sqlite3.html",
        "Python Software Foundation",
        "SQLite 连接、参数化查询、事务与行访问",
    ),
    "robotparser": (
        "Python 标准库：urllib.robotparser",
        "https://docs.python.org/zh-cn/3/library/urllib.robotparser.html",
        "Python Software Foundation",
        "robots.txt 解析与抓取许可检查",
    ),
    "statistics": (
        "Python 标准库：statistics",
        "https://docs.python.org/zh-cn/3/library/statistics.html",
        "Python Software Foundation",
        "均值、中位数、众数、方差与描述性统计",
    ),
}


CHAPTERS: tuple[ChapterSpec, ...] = (
    (
        "getting-started",
        "第 1 章 Python 起步与程序执行",
        "建立源代码、解释器、输入和输出的正确心智模型",
        (
            ("interpreter", "解释器与交互模式", "区分交互命令和脚本执行", "终端会自动理解 Python 语法", ">>> 1 + 2", "interpreter"),
            ("source-file", "源文件与执行顺序", "按语句顺序追踪脚本执行", "扩展名决定程序一定正确", "print('第一步')\nprint('第二步')", "interpreter"),
            ("expression-statement", "表达式与语句", "区分产生值的表达式和执行动作的语句", "每一行代码都会显示结果", "result = 2 + 3", "introduction"),
            ("print-output", "print 与标准输出", "使用 print 组织可观察输出", "逗号连接等同字符串相加", "print('总分', 95)", "introduction"),
            ("input-text", "input 与文本输入", "解释 input 总是返回字符串", "输入数字会自动成为 int", "name = input('姓名：')", "introduction"),
            ("trace-first-program", "手工追踪第一个程序", "记录每步变量和输出变化", "只看最终输出即可理解程序", "age = int(input())\nprint(age + 1)", "introduction"),
        ),
    ),
    (
        "values-types",
        "第 2 章 值、变量、类型与运算",
        "理解名称绑定、基础类型和表达式求值",
        (
            ("name-binding", "变量与名称绑定", "把赋值解释为名称绑定到对象", "变量是固定类型的盒子", "x = 1\nx = '一'", "executionmodel"),
            ("identifiers-keywords", "标识符、关键字与命名", "遵守标识符规则并识别不能重绑定的关键字", "任意 Unicode 文本都可直接作为变量名", "student_score = 95", "lexical"),
            ("numeric-types", "整数与浮点数", "选择 int 或 float 表示数量", "浮点数能精确表示所有小数", "print(0.1 + 0.2)", "stdtypes"),
            ("boolean-values", "布尔值与真值测试", "用 bool 解释条件上下文", "只有 True 和 False 可作条件", "print(bool([]), bool([0]))", "stdtypes"),
            ("type-conversion", "显式类型转换", "安全地转换文本、整数和浮点数", "int 会四舍五入浮点数", "print(int(3.9))", "stdtypes"),
            ("arithmetic-operators", "算术与整除取余", "解释 /、//、% 和 **", "整除总是向零截断", "print(-7 // 3, -7 % 3)", "stdtypes"),
            ("operator-precedence", "优先级与括号", "按优先级计算复合表达式", "代码从左到右无条件计算", "print(2 + 3 * 4)", "stdtypes"),
            ("binary-bitwise", "进制、位运算与掩码", "解释二进制表示并用位运算读取或设置标志位", "按位与和逻辑 and 完全相同", "flags = 0b1010\nprint(flags & 0b0010)", "stdtypes"),
        ),
    ),
    (
        "strings-io",
        "第 3 章 字符串与格式化输入输出",
        "把字符串作为不可变序列处理并形成可靠输入输出",
        (
            ("string-literals", "字符串字面量与转义", "正确表示引号、换行和原始字符串", "反斜杠总是普通字符", "print('第一行\\n第二行')", "stdtypes"),
            ("string-index", "索引与负索引", "读取字符串中的单个字符", "负索引从零开始", "print('Python'[-1])", "stdtypes"),
            ("string-slice", "切片与半开区间", "使用 start:stop:step 提取片段", "切片包含 stop 位置", "print('Python'[1:4])", "stdtypes"),
            ("string-methods", "常用字符串方法", "用 strip、split、join 处理文本", "字符串方法会原地修改原串", "print(','.join(['甲', '乙']))", "stdtypes"),
            ("f-strings", "f-string 格式化", "在模板中安全插入值并控制格式", "花括号内容只允许变量名", "score = 92.5\nprint(f'{score:.1f}')", "inputoutput"),
            ("parse-input", "输入校验与解析", "把一行输入拆分并转换为目标类型", "split 会自动转换数字", "a, b = map(int, input().split())", "inputoutput"),
        ),
    ),
    (
        "branching",
        "第 4 章 条件判断与分支设计",
        "用互斥、覆盖完整的条件表达业务规则",
        (
            ("comparisons", "比较与逻辑运算", "组合比较、and、or 和 not", "and 两边一定都会执行", "print(0 < 3 < 10)", "stdtypes"),
            ("if-else", "if/else 双分支", "为互斥结果设计完整分支", "else 需要重复条件", "print('及格' if 60 >= 60 else '未及格')", "controlflow"),
            ("elif-chain", "elif 多分支", "按优先级组织多段互斥条件", "所有为真的分支都会执行", "score = 85\nif score >= 90: print('A')\nelif score >= 80: print('B')", "controlflow"),
            ("nested-conditions", "嵌套条件", "在有依赖的判断中使用嵌套", "嵌套越深逻辑越准确", "if logged_in:\n    if is_admin:\n        print('管理')", "controlflow"),
            ("guard-clauses", "卫语句与提前返回", "用卫语句减少无效嵌套", "函数只能在末尾 return", "def ratio(a, b):\n    if b == 0: return None\n    return a / b", "controlflow"),
            ("branch-boundaries", "分支边界测试", "从阈值两侧和等值设计测试", "测试一个典型值即可", "for score in (59, 60, 61): print(score >= 60)", "unittest"),
        ),
    ),
    (
        "loops",
        "第 5 章 循环、状态与边界",
        "准确推导循环次数、终止条件和边界行为",
        (
            ("for-range", "for 与 range", "解释 range 的半开区间和步长", "range 会包含 stop", "print(list(range(1, 5)))", "controlflow"),
            ("while-state", "while 与状态更新", "识别循环状态、条件和推进步骤", "条件会自动改变循环变量", "n = 3\nwhile n > 0:\n    n -= 1", "controlflow"),
            ("break-continue", "break、continue 与 else", "控制单轮和整个循环的退出", "continue 会结束整个循环", "for n in range(3):\n    if n == 1: continue\n    print(n)", "controlflow"),
            ("enumerate-zip", "enumerate 与 zip", "同步遍历索引和多个序列", "遍历列表必须手工维护索引", "for i, ch in enumerate('abc'): print(i, ch)", "controlflow"),
            ("nested-loops", "嵌套循环与复杂度直觉", "计算嵌套循环执行次数", "两层循环总执行 n+n 次", "for i in range(2):\n    for j in range(3): print(i, j)", "controlflow"),
            ("loop-boundaries", "循环边界综合调试", "用不变量和边界样例定位少一次或多一次", "调整 range 终点无需重新推导", "total = 0\nfor n in range(1, 6): total += n", "controlflow"),
        ),
    ),
    (
        "collections",
        "第 6 章 列表、元组、字典与集合",
        "根据数据语义选择集合并理解可变性",
        (
            ("lists", "列表增删改查", "使用列表维护有序可变数据", "append 返回修改后的列表", "items = [1]\nitems.append(2)", "datastructures"),
            ("tuples-unpacking", "元组与解包", "用元组表达固定结构并解包", "单元素元组只需括号", "point = (3, 4)\nx, y = point", "datastructures"),
            ("dictionaries", "字典键值映射", "按键读取、更新和遍历映射", "字典索引依赖位置", "scores = {'李': 90}\nprint(scores['李'])", "datastructures"),
            ("sets", "集合与去重运算", "使用集合去重和计算交并差", "集合保持插入顺序契约", "print({1, 2} & {2, 3})", "datastructures"),
            ("comprehensions", "推导式", "把映射与筛选组合为清晰表达式", "推导式必然比循环更易读", "print([n*n for n in range(5) if n % 2])", "datastructures"),
            ("choose-collection", "集合类型选型", "按顺序、唯一性和查找方式选型", "所有场景都用列表最简单", "records = {'学号': {'姓名': '小林'}}", "datastructures"),
        ),
    ),
    (
        "functions",
        "第 7 章 函数、参数与分解",
        "把问题分解为有清晰契约的可复用函数",
        (
            ("define-call", "定义与调用函数", "区分函数对象、调用和返回结果", "写出 def 就会立即运行函数体", "def greet(): return '你好'\nprint(greet())", "controlflow"),
            ("parameters-return", "参数与返回值", "用参数输入和 return 输出结果", "print 与 return 可以互换", "def area(w, h): return w * h", "controlflow"),
            ("object-argument-semantics", "对象共享与参数传递", "根据名称绑定和对象可变性预测调用后的状态", "函数调用会深拷贝所有实参", "items = []\ndef add(values): values.append(1)\nadd(items)", "executionmodel"),
            ("positional-keyword", "位置参数与关键字参数", "按函数签名正确传参", "关键字参数可放在位置参数之前", "print(round(number=3.14159, ndigits=2))", "controlflow"),
            ("variadic-arguments", "*args 与 **kwargs", "收集数量可变的位置和关键字参数", "星号参数会丢失原有顺序", "def collect(*items): return list(items)", "controlflow"),
            ("function-contract", "函数契约与文档", "写清前置条件、输出和异常", "函数名足以表达所有约束", "def positive(n: int) -> bool:\n    return n > 0", "controlflow"),
            ("decompose-problem", "自顶向下分解", "把输入、处理和输出拆成小函数", "函数越多程序一定越好", "def main():\n    data = read_data()\n    print(summarize(data))", "controlflow"),
        ),
    ),
    (
        "scope",
        "第 8 章 作用域、闭包与名称解析",
        "依据执行模型解释名称绑定和 LEGB 查找",
        (
            ("namespace-binding", "命名空间与绑定", "说明模块、函数和类代码块的绑定位置", "名称直接存放值本身", "x = []\ny = x\nprint(x is y)", "executionmodel"),
            ("legb-resolution", "LEGB 名称解析", "按局部、闭包、全局、内置顺序查找", "Python 从调用者函数查找变量", "x = '全局'\ndef f(): print(x)", "executionmodel"),
            ("global-statement", "global 与模块状态", "判断何时发生全局名称重绑定", "读取全局名称必须写 global", "count = 0\ndef inc():\n    global count\n    count += 1", "executionmodel"),
            ("nonlocal-closure", "nonlocal 与闭包", "在闭包中重绑定外层函数名称", "nonlocal 会访问模块全局变量", "def outer():\n    n = 0\n    def inc():\n        nonlocal n", "executionmodel"),
            ("late-binding", "闭包的延迟绑定", "解释循环变量在闭包调用时解析", "lambda 会复制定义时的所有变量", "funcs = [lambda i=i: i for i in range(3)]", "executionmodel"),
            ("scope-unbound-local", "UnboundLocalError 深度调试", "从代码块绑定规则定位局部变量遮蔽", "运行到赋值行前名称仍按全局解析", "x = 1\ndef f():\n    print(x)\n    x = 2", "executionmodel"),
        ),
    ),
    (
        "defaults",
        "第 9 章 默认参数、可变对象与 API 设计",
        "掌握定义时求值并避免共享可变状态",
        (
            ("default-evaluation", "默认参数的求值时机", "说明默认表达式在函数定义时求值一次", "每次调用都会重新计算默认值", "stamp = object()\ndef f(value=stamp): return value", "defaults_faq"),
            ("mutable-default-trap", "可变默认参数共享陷阱", "复现并修复跨调用共享列表的问题", "函数返回后默认列表会自动销毁", "def add(x, items=[]):\n    items.append(x)\n    return items", "defaults_faq"),
            ("none-sentinel", "None 哨兵模式", "用 None 在调用时创建新容器", "None 与空列表表达同一意图", "def add(x, items=None):\n    if items is None: items = []", "defaults_faq"),
            ("default-factory", "默认工厂", "用工厂为每个实例创建独立可变值", "dataclass 允许直接用 [] 作默认值", "field(default_factory=list)", "dataclasses"),
            ("keyword-only", "仅限关键字参数", "用 * 提升调用处参数可读性", "星号后的参数不能提供默认值", "def connect(host, *, timeout=3): pass", "controlflow"),
            ("api-default-design", "默认值与 API 契约", "区分缺省、空值和显式提供值", "所有可选参数都应默认 None", "MISSING = object()\ndef update(value=MISSING): pass", "defaults_faq"),
        ),
    ),
    (
        "modules-packages",
        "第 10 章 模块、包与代码组织",
        "用模块边界组织代码并理解导入行为",
        (
            ("module-import", "模块与 import", "解释导入、模块对象和名称绑定", "import 会把模块代码复制到当前文件", "import math\nprint(math.sqrt(9))", "modules"),
            ("venv-dependencies", "虚拟环境与依赖隔离", "为项目创建独立环境并记录可复现依赖", "全局安装包不会造成项目间版本冲突", "python -m venv .venv", "venv"),
            ("import-forms", "导入形式与别名", "比较 import、from import 和别名", "通配符导入能明确依赖", "from statistics import mean as average", "modules"),
            ("module-main", "__name__ 与程序入口", "区分作为脚本运行和作为模块导入", "导入模块时 __name__ 总是 __main__", "if __name__ == '__main__':\n    main()", "modules"),
            ("packages", "包与相对导入", "按目录和包组织多个模块", "有目录就一定是可导入包", "from .models import Student", "modules"),
            ("standard-library", "标准库检索与使用", "从官方文档选择标准库能力", "常用功能都应自行实现", "from collections import Counter", "modules"),
            ("dependency-boundaries", "依赖方向与接口", "减少循环导入并把共享契约下沉", "循环导入只与文件名有关", "# domain <- service <- interface", "modules"),
        ),
    ),
    (
        "files-errors",
        "第 11 章 文件、JSON 与异常处理",
        "可靠处理外部数据、资源生命周期和失败路径",
        (
            ("pathlib-paths", "pathlib 路径", "用 Path 组合并检查相对路径", "字符串拼接路径在所有系统都可靠", "path = Path('data') / 'scores.txt'", "pathlib"),
            ("sqlite-persistence", "SQLite 持久化入门", "使用参数化查询和事务保存结构化数据", "把输入拼进 SQL 字符串与参数化查询同样安全", "connection.execute('SELECT * FROM scores WHERE id = ?', (student_id,))", "sqlite3"),
            ("text-files", "文本文件与编码", "显式选择编码并读写文本", "文本文件天然都是 UTF-8", "Path('a.txt').write_text('你好', encoding='utf-8')", "inputoutput"),
            ("with-resources", "with 与资源清理", "用上下文管理器保证文件关闭", "正常运行时才需要关闭文件", "with open('a.txt', encoding='utf-8') as file:\n    text = file.read()", "inputoutput"),
            ("json-data", "JSON 序列化", "区分 Python 对象与 JSON 数据", "JSON 能直接保存任意 Python 对象", "payload = json.dumps({'score': 90}, ensure_ascii=False)", "inputoutput"),
            ("handle-exceptions", "精确捕获异常", "只捕获可处理的异常并保留意外失败", "except Exception 后 pass 最稳妥", "try:\n    value = int(text)\nexcept ValueError:\n    value = 0", "errors"),
            ("raise-cleanup", "抛出、自定义与清理", "用 raise 表达契约失败并理解 finally", "raise 只能用于系统异常", "if age < 0:\n    raise ValueError('年龄不能为负')", "errors"),
            ("assert-exception-test", "assert、异常与测试职责", "区分内部断言、运行时输入校验和测试断言", "assert 可替代所有用户输入校验", "assert total >= 0, '总数不应为负'", "simple_statements"),
        ),
    ),
    (
        "objects-classes",
        "第 12 章 对象、类与数据建模",
        "用对象封装状态和行为并选择适度抽象",
        (
            ("class-instance", "类与实例", "区分类对象、实例对象和构造过程", "类定义等同创建一个实例", "class Student:\n    pass\ns = Student()", "classes"),
            ("encapsulation-polymorphism", "封装、私有约定与多态", "用统一协议调用不同实现并理解下划线命名约定", "双下划线属性在运行时绝对不可访问", "def render(item):\n    return item.to_text()", "classes"),
            ("attributes-methods", "属性与方法", "用 self 访问实例状态", "self 是 Python 保留关键字", "class Counter:\n    def inc(self): self.value += 1", "classes"),
            ("class-instance-vars", "类变量与实例变量", "避免在类变量中意外共享可变状态", "实例会复制所有类变量", "class Team:\n    members = []", "classes"),
            ("inheritance", "继承与组合", "按 is-a 与 has-a 选择复用方式", "继承总比组合减少耦合", "class Admin(User):\n    pass", "classes"),
            ("dataclass-model", "dataclass 数据模型", "用数据类生成样板方法并声明字段", "dataclass 会验证运行时类型", "@dataclass\nclass Point:\n    x: int\n    y: int", "dataclasses"),
            ("object-design", "对象职责与不变量", "把验证和状态变化放在清晰边界", "一个类应负责整个业务流程", "def rename(self, name):\n    if not name: raise ValueError", "classes"),
        ),
    ),
    (
        "recursion",
        "第 13 章 递归、调用栈与算法思维",
        "从基线、递推关系和栈帧证明递归终止",
        (
            ("recursive-model", "递归问题模型", "识别可缩小为同类子问题的结构", "出现函数自调用就是正确递归", "def countdown(n):\n    if n > 0: countdown(n - 1)", "recursion"),
            ("base-case", "基线条件", "设计覆盖最小输入的停止条件", "递归会在数据耗尽时自动停止", "def fact(n):\n    if n == 0: return 1", "recursion"),
            ("recursive-step", "递推步骤与规模缩减", "证明每次调用都靠近基线", "参数变化就一定会终止", "return n * fact(n - 1)", "recursion"),
            ("recursion-stack", "调用栈深度追踪", "逐帧记录参数、暂停点和返回值", "递归调用共享同一组局部变量", "# fact(3) -> fact(2) -> fact(1)", "recursion"),
            ("tree-recursion", "树形递归与重复计算", "识别分支递归的重复子问题", "斐波那契递归只产生 n 个调用", "return fib(n - 1) + fib(n - 2)", "recursion"),
            ("recursion-iteration", "递归与迭代转换", "在深度和状态成本间选择实现", "递归版本必然更快", "result = 1\nfor value in range(2, n + 1): result *= value", "recursion"),
        ),
    ),
    (
        "iteration-testing",
        "第 14 章 迭代器、测试与应用拓展",
        "用惰性数据流、自动化测试和标准库能力完成可维护小项目",
        (
            ("iterator-protocol", "迭代协议", "解释 iter、next 与 StopIteration", "可迭代对象就是迭代器", "iterator = iter([1, 2])\nprint(next(iterator))", "functional"),
            ("generator-yield", "生成器与 yield", "理解生成器暂停和恢复执行", "调用生成器函数会立即运行函数体", "def numbers():\n    yield 1\n    yield 2", "functional"),
            ("lazy-pipeline", "惰性数据管道", "组合生成器处理流式数据", "生成器会一次性保存全部结果", "squares = (n*n for n in range(10))", "functional"),
            ("unit-tests", "unittest 与断言", "为函数编写独立可重复测试", "没有抛异常就代表测试通过", "class TestTotal(unittest.TestCase):\n    def test_empty(self): self.assertEqual(total([]), 0)", "unittest"),
            ("test-boundaries", "边界、异常与回归测试", "从等价类和失败历史选择用例", "测试数量越多质量一定越高", "with self.assertRaises(ValueError):\n    parse_age('-1')", "unittest"),
            ("responsible-robots", "robots 规则与负责任抓取", "在自动获取站点内容前检查 robots 规则和访问边界", "公开网页默认允许任意频率抓取", "parser = RobotFileParser()\nparser.set_url('/robots.txt')", "robotparser"),
            ("descriptive-statistics", "描述性统计入门", "用均值、中位数和离散程度描述一组数据", "平均数总能代表典型水平", "print(mean([60, 80, 100]))", "statistics"),
            ("integrated-project", "综合项目与复盘", "整合模块、文件、异常和测试交付小项目", "功能跑通后无需整理契约和测试", "def main() -> None:\n    records = load_records()\n    print(report(records))", "unittest"),
        ),
    ),
)

DEEP_NODE_KEYS = {
    "loop-boundaries",
    "scope-unbound-local",
    "mutable-default-trap",
    "recursion-stack",
}


def build_document() -> dict[str, Any]:
    course_id = stable_id("course", "university-python-general")
    source_assets = [
        {
            "source_id": stable_id("source", key),
            "title": title,
            "url": url,
            "publisher": publisher,
            "content_scope": scope,
            "version": VERSION,
        }
        for key, (title, url, publisher, scope) in SOURCES.items()
    ]
    policy_ids = {
        "foundation": stable_id("mastery-policy", "foundation"),
        "deep": stable_id("mastery-policy", "deep"),
    }
    mastery_policies = [
        {
            "policy_id": policy_ids["foundation"],
            "name": "通识基础掌握策略",
            "pass_threshold": 0.8,
            "stable_attempts": 2,
            "max_support_level": 1,
            "min_transfer_score": 0.6,
            "review_intervals_days": [1, 3, 7],
            "version": VERSION,
        },
        {
            "policy_id": policy_ids["deep"],
            "name": "核心难点稳定掌握策略",
            "pass_threshold": 0.9,
            "stable_attempts": 3,
            "max_support_level": 0,
            "min_transfer_score": 0.8,
            "review_intervals_days": [1, 2, 7, 14],
            "version": VERSION,
        },
    ]
    chapters: list[dict[str, Any]] = []
    nodes: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    questions: list[dict[str, Any]] = []
    tests: list[dict[str, Any]] = []
    previous_node_id: str | None = None

    for chapter_order, (chapter_key, title, chapter_objective, node_specs) in enumerate(
        CHAPTERS, start=1
    ):
        chapter_id = stable_id("chapter", chapter_key)
        chapter_node_ids: list[str] = []
        for node_key, node_title, objective, misconception, example, source_key in node_specs:
            node_id = stable_id("node", node_key)
            diagnostic_id = stable_id("question", f"{node_key}:diagnostic")
            practice_id = stable_id("question", f"{node_key}:practice")
            diagnostic_test_id = stable_id("test", f"{node_key}:diagnostic")
            practice_test_id = stable_id("test", f"{node_key}:practice")
            source_id = stable_id("source", source_key)
            is_deep = node_key in DEEP_NODE_KEYS
            chapter_node_ids.append(node_id)
            nodes.append(
                {
                    "node_id": node_id,
                    "title": node_title,
                    "chapter_id": chapter_id,
                    "learning_objectives": [objective],
                    "prerequisites": [previous_node_id] if previous_node_id else [],
                    "misconceptions": [misconception],
                    "examples": [example],
                    "diagnostic_items": [diagnostic_id],
                    "practice_templates": [practice_id],
                    "mastery_policy_id": policy_ids["deep" if is_deep else "foundation"],
                    "source_ids": [source_id],
                    "version": VERSION,
                }
            )
            errors.append(
                {
                    "error_id": stable_id("error", node_key),
                    "node_ids": [node_id],
                    "title": f"{node_title}：典型误区",
                    "symptom": f"学习者在“{node_title}”任务中给出稳定但错误的解释或边界结果",
                    "misconception": misconception,
                    "diagnosis_prompts": [f"请逐步解释“{example}”中每一步的值或控制流。"],
                    "remediation": [f"回到“{objective}”，再用一个正常值和一个边界值验证。"],
                    "source_ids": [source_id],
                    "version": VERSION,
                }
            )
            questions.extend(
                [
                    {
                        "question_id": diagnostic_id,
                        "node_id": node_id,
                        "kind": "MULTIPLE_CHOICE",
                        "prompt_template": (
                            f"关于“{node_title}”，哪项分析符合 Python 语义？"
                            f"A. {objective}；B. {misconception}"
                        ),
                        "parameter_schema": {},
                        "answer_schema": {"type": "string", "const": "A"},
                        "test_case_ids": [diagnostic_test_id],
                        "source_ids": [source_id],
                        "version": VERSION,
                    },
                    {
                        "question_id": practice_id,
                        "node_id": node_id,
                        "kind": "CODE_WRITING",
                        "prompt_template": (
                            f"围绕“{node_title}”编写最小程序，输出“完成：{node_title}”，"
                            f"并用注释说明如何{objective}。"
                        ),
                        "parameter_schema": {},
                        "answer_schema": {"type": "string", "minLength": 1},
                        "test_case_ids": [practice_test_id],
                        "source_ids": [source_id],
                        "version": VERSION,
                    },
                ]
            )
            tests.extend(
                [
                    {
                        "test_id": diagnostic_test_id,
                        "node_id": node_id,
                        "kind": "RETURN_VALUE",
                        "input": "",
                        "expected": "A",
                        "hidden": False,
                        "timeout_ms": 1000,
                        "version": VERSION,
                    },
                    {
                        "test_id": practice_test_id,
                        "node_id": node_id,
                        "kind": "STDOUT",
                        "input": "",
                        "expected": f"完成：{node_title}\n",
                        "hidden": True,
                        "timeout_ms": 1000,
                        "version": VERSION,
                    },
                ]
            )
            previous_node_id = node_id

        chapters.append(
            {
                "chapter_id": chapter_id,
                "course_id": course_id,
                "order": chapter_order,
                "title": title,
                "learning_objectives": [chapter_objective],
                "node_ids": chapter_node_ids,
                "version": VERSION,
            }
        )

    return {
        "schema_version": VERSION,
        "content_version": VERSION,
        "course": {
            "course_id": course_id,
            "slug": "university-python-general",
            "title": "高校通识 Python",
            "audience": "零基础或基础薄弱的高校非计算机与计算机专业学生",
            "language": "zh-CN",
            "chapter_ids": [chapter["chapter_id"] for chapter in chapters],
            "required_chapter_count": 14,
            "minimum_node_count": 80,
            "required_deep_unit_count": 4,
            "deep_unit_node_ids": [
                stable_id("node", node_key) for node_key in sorted(DEEP_NODE_KEYS)
            ],
            "version": VERSION,
        },
        "chapters": chapters,
        "nodes": nodes,
        "sources": source_assets,
        "error_patterns": errors,
        "question_templates": questions,
        "test_cases": tests,
        "mastery_policies": mastery_policies,
    }


def write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> None:
    raw_document = build_document()
    bundle = CourseAssetBundle.model_validate(raw_document)
    document = bundle.model_dump(mode="json")
    report = validate_course_document(document)
    if not report.valid:
        formatted = ", ".join(f"{item.code}:{item.path}" for item in report.findings)
        raise SystemExit(f"refusing to publish invalid course assets: {formatted}")

    asset_dir = ROOT / "knowledge" / "python-general" / "v1"
    schema_dir = ROOT / "knowledge" / "schemas" / "v1"
    write_json(asset_dir / "course-bundle.json", document)
    write_json(asset_dir / "validation-report.json", report.model_dump(mode="json"))
    for filename, schema in generate_asset_schemas().items():
        write_json(schema_dir / filename, schema)


if __name__ == "__main__":
    main()
