# 动态校验的局部计算模型

## 动态校验尚未通过

`builder/security_codec.py` 只实现五段源码辅助的纯值模型，不是完整 `__zp_stoken__` 生成器。正常扫码登录和账号查询已有独立成功记录，但职位查询仍停在历史 code 37；本次没有计算真实会话的安全 Cookie，也没有重试业务请求。

这五段对应本次 `e5a1794d.js` 的分派入口，原文件 SHA-256 为 `641c23791eddaceea84d307930bf90a2ccd2d0c93eaa07175426b085d87fa65a`；入口编号只对这份文件有效，不能推广到其他动态版本。[公开动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)

## 已拆出的计算

| 入口 | 局部行为 | 独立实现与边界 |
| --- | --- | --- |
| `15983` | 逐项读取字符串的 `charCodeAt`，得到 UTF-16 code unit 数组，不是 MD5。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) | `utf16_units_15983` 保留代理项；不把 Python Unicode code point 当作 JS code unit。 |
| `5810` | 输入元素先加 3，再与循环使用的键数组元素异或。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) | `xor_mix_5810` 只覆盖输入字节、非空 UTF-16 单元键；不添加源码没有的 `& 255`。 |
| `10702` | 逐元素异或 1、加 1、逆序、加 8、再逆序；在普通数组值域中等价于原顺序的 `(x ^ 1) + 9`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) | `offset_transform_10702` 返回新列表，只复现值，不复现原数组的就地修改、Proxy 或 typed-array 行为。 |
| `303` | 按 `<128`、`<2048`、其余三条分支展开为 1、2、3 个字节，没有四字节 Unicode 标量路径。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) | `numeric_utf8_303` 仅接收 `0..65535` 的整数；代理项分别编码，不直接替换成完整 Unicode UTF-8 库调用。 |
| `18580` | 字节数组分支使用标准 Base64 字母表、三字节分组和补位；字符串输入另调用入口 `3108`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) | `base64_bytes_18580` 只实现字节数组分支，字符串输入被明确拒绝。 |

主入口的尾部依次调用 `5810`、数组拼接、`10702`、`303` 和 `18580`；本项目没有把“这些尾部函数可解释”偷换成“拼接前的全部真实数据已恢复”。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)

### 为什么不能直接截成字节

中间变换存在超过 255 的正常数值，后面才进入数值编码；若提前截成字节，输出会改变。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) 下面使用完全合成的输入，只演示这个边界，不是某次真实会话的材料。

```python
from builder.security_codec import (
    utf16_units_15983,
    xor_mix_5810,
    offset_transform_10702,
    numeric_utf8_303,
    base64_bytes_18580,
)

key_units = utf16_units_15983("0")
mixed = xor_mix_5810([255], key_units)
assert mixed == [306]
transformed = offset_transform_10702(mixed)
assert transformed == [316]
encoded = numeric_utf8_303(transformed)
assert encoded == bytes.fromhex("c4bc")
assert base64_bytes_18580(encoded) == "xLw="
# 这里只是局部算术示例，不包含完整输入包，也不是有效 stoken。
```

## 静态证明的条件

控制流整理保留不透明调用和宿主属性访问；对 `!typeof value` 等正常求值后恒假的条件，可以做语言语义化简，但不因此断言属性读取、getter 或外部环境一定不会抛错。分析没有运行目标脚本，也没有安装假的 `window`、指纹或随机输入来模拟真实验证通过。

- **输入域**：Python 接口只接受普通、稠密的整数序列或明确的字符串，各阶段范围分别检查；最大 65536 个元素是本地防误用限制，不是恢复出的服务端限制。
- **副作用**：值模型复制输入，不模拟原数组别名、就地修改、被改写的原生方法、代理对象、属性 getter 和脚本异常吞掉行为。
- **环境条件**：某些宿主引用只参与正常完成路径上的常量化条件，不能仅因出现 `window` 就认定其具体属性值是最终指纹输入，也不能因此断言整个算法不依赖环境。
- **复现状态**：七组合成向量、全字节取值和编码边界在独立 Python/JavaScript 模型间一致；还没有拿真实浏览器中原函数的改变输入结果作对照。

### 原文件位置

以下是关键操作的锚点，不是完整函数连续范围；源文件为 ASCII，所以这些锚点的 UTF-16 与 UTF-8 数值恰好一致，全部按 0 起始、右端不包含计算。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js)

| 入口 | 关键原始范围 |
| --- | --- |
| `15983` | 方法读取 `[26834,26850)`，字符单元调用 `[106401,106424)`，写入 `[198385,198409)`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) |
| `5810` | 加法 `[287249,287264)`，循环键下标 `[54784,54800)`，异或 `[51139,51155)`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) |
| `10702` | 异或 `[50810,50825)`，加 1 `[63258,63274)`，第一次逆序 `[166825,166846)`，加 8 `[238140,238156)`，第二次逆序 `[185779,185801)`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) |
| `303` | 数值分支 `[70498,70511)`、`[129798,129814)`，单字节写入 `[230949,230970)`，多字节写入见机器报告。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) |
| `18580` | 字母表拼接末步 `[141150,141166)`，四个字符调用 `[218245,218269)`、`[149660,149683)`、`[250256,250281)`、`[164697,164722)`，返回 `[99336,99347)`。[动态脚本](https://www.zhipin.com/web/passport/zp/security-js/e5a1794d.js) |

## 测试和剩余缺口

`tests/test_security_codec.py` 的 13 项检查和 `tests/test_security_codec_reference.mjs` 的 4 项检查已在工作区通过，参考向量写在 `tests/fixtures/security_codec_vectors.json`。JavaScript 参考由项目独立编写，不导入第三方 bundle；这些结果证明限定模型的一致性，不是目标运行等价或服务器接受证明。

```bash
python -m unittest tests.test_security_codec -v
npm run test:security-codec
```

完整输入包、挑战参数序列化、初始化共享状态及环境采样仍需按同一版本继续核对；真实浏览器运行对照、业务请求成功和对应的 cURL 逐项比较也仍未完成。机器状态在 `reports/security-codec-current.json`，完整链的阻塞说明继续保留在 `docs/SECURITY_PROTOCOL.md`。
