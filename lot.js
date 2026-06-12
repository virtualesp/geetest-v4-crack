const parser = require("@babel/parser");
const traverse = require("@babel/traverse").default;
const t = require("@babel/types");
const generator = require("@babel/generator").default;
const fs = require("fs");

/**
 * 根据点分隔的路径字符串构建一个嵌套对象。
 * @param {string} path - 点分隔的路径字符串，例如 'a.b.c'。
 * @returns {Object} 嵌套对象。
 */
function buildNestedObject(path) {
    const keys = path.split('.');
    let result = keys.pop(); // 最内层的值

    // 从后往前构造对象
    while (keys.length) {
        const key = keys.pop();
        result = { [key]: result };
    }

    return result;
}

/**
 * 解析类似 n[13:18] 的切片规则，返回计算后的值
 * @param {string} rule - 切片规则字符串，如 'n[13:18]'
 * @param {string} lotNumber - 用于切片的字符串
 * @returns {string} 切片后的结果
 */
function parseSliceRule(rule, lotNumber) {
    // 匹配 n[start:end] 格式
    const match = rule.match(/n\[(\d+):(\d+)\]/);
    if (match) {
        const start = parseInt(match[1]);
        const end = parseInt(match[2]) + 1; // +1 因为原规则是闭区间
        return lotNumber.slice(start, end);
    }
    // 如果不匹配，返回原值
    return rule;
}

/**
 * 根据点分隔的路径字符串和指定的值构建一个嵌套对象。
 * @param {string} path - 点分隔的路径字符串，例如 'a.b.c'。
 * @param {*} finalValue - 作为最内层属性值的实际数据。
 * @param {string} lotNumber - 用于计算切片的 lot_number 字符串。
 * @returns {Object} 嵌套对象。
 */
function buildNestedObjectWithValue(path, finalValue, lotNumber) {
    const keys = path.split('.');

    // 如果 finalValue 是切片规则字符串，计算实际值
    let result = finalValue;
    if (typeof finalValue === 'string' && finalValue.includes('n[')) {
        result = parseSliceRule(finalValue, lotNumber);
    }

    // 从后往前构造对象
    while (keys.length) {
        const key = keys.pop();
        result = { [key]: result };
    }

    return result;
}

//提取js动态参数

/**
 * 从混淆的 JavaScript 代码中提取动态参数。
 * @param {string} jscode - 包含混淆逻辑的 JavaScript 代码字符串。
 * @param {string} lotNumber - 用于参数计算的批号/字符串。
 * @returns {Object} 包含 'first', 'two', 和 'rules' 结果的对象。
 */
function getParams(jscode, lotNumber) {
    // 将js代码修转成AST语法树
    let ast = parser.parse(jscode);
    let firstCode = generator(ast.program.body[0]).code
    let firstAst = parser.parse(firstCode);

    // 遍历第一个 AST，提取解密函数
    traverse(firstAst, {
        'ReturnStatement': function (path) {
            let node = path.node
            if (node.argument.type == 'ObjectExpression') {
                let code = generator(node.argument.properties[0].value).code
                let newCode = `decrypt = ${code}`
                // 动态执行代码以获取 decrypt 函数
                eval(newCode)
            }
        }
    })

    // 提取包含参数键值对的表达式
    let twoCode = generator(ast.program.body[5].expression.argument.callee.body.body[0].expression.expressions[0]).code
    let twoAst = parser.parse(twoCode);

    let res = {}

    // 遍历第二个 AST，提取和解密键值对
    traverse(twoAst, {
        'ObjectProperty': function (path) {
            let node = path.node
            let key = node.key.value
            if (!key) {
                key = node.key.name
            }
            // 假设值是 decrypt 函数调用的参数
            let value = node.value.arguments[0].value
            // 使用前面获取的 decrypt 函数进行解密
            res[key] = decrypt(value)
        }
    })

    // 开始处理第二个参数的键（key）和值（value）的动态拼接逻辑
    const split = Object.keys(res)[1].split('+')
    let isSplit = []
    for (let i = 0; i < split.length; i++) {
        if (split[i] === '.') { isSplit.push(i) }
    }

    // 提取 key 中用于 slice 的索引 [a:b]
    const keyIndex = Object.keys(res)[1].match(/\[(.*?)\]/g).map(match => match.slice(1, -1)).map(item => item.split(':'));
    // 提取 value 中用于 slice 的索引 [a:b]
    const valueIndex = Object.values(res)[1].match(/\[(.*?)\]/g).map(match => match.slice(1, -1)).map(item => item.split(':'));

    // 获取第二个参数的原始解密结果
    const finalDecryptedValue = Object.values(res)[1];

    let keyRes = ''
    let valueRes = ''
    let handlerNum = 0

    // 根据索引和 lotNumber 拼接 keyRes (路径)
    for (let i = 0; i < keyIndex.length; i++) {
        let first = parseInt(keyIndex[i][0])
        let two = 1 < keyIndex[i]['length'] ? parseInt(keyIndex[i][1]) + 1 : parseInt(keyIndex[i][0]) + 1;
        let tmp = lotNumber.slice(first, two)
        if (isSplit.includes(i + 1 + handlerNum)) {
            handlerNum += 1
            tmp += '.'
        }
        keyRes += tmp
    }

    // 根据索引和 lotNumber 拼接 valueRes
    for (let item of valueIndex) {
        let first = parseInt(item[0])
        let two = 1 < item['length'] ? parseInt(item[1]) + 1 : parseInt(item[0]) + 1;
        valueRes += lotNumber.slice(first, two)
    }

    // 构造最终结果
    let firstRes = {}
    firstRes[Object.keys(res)[0]] = Object.values(res)[0]

    // 使用 buildNestedObjectWithValue 函数构建嵌套对象
    let path = keyRes
    let twoRes = buildNestedObjectWithValue(path, finalDecryptedValue, lotNumber)

    // 构造规则对象 - 用于 Python 端在运行时重新计算
    // 规则包含：keyIndex（用于构建嵌套路径）、isSplit（分隔符位置）、valueRule（最内层值的计算规则）
    let rules = {
        keyIndex: keyIndex,
        isSplit: isSplit,
        valueRule: finalDecryptedValue
    }

    return {
        'first': firstRes,
        'two': twoRes,
        'rules': rules
    }
}


let encode_file = "bcaptcha.js"

// 读取需要解码的js文件, 注意文件编码为utf-8格式
let jscode = fs.readFileSync(encode_file, { encoding: "utf-8" });
console.log(JSON.stringify(getParams(jscode, "ad186e5a651c4e14985954242b472592"), null, 2))