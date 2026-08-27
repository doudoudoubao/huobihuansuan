"""货币元数据与别名词典。

设计目标：用户怎么随手打，都能认出来。
支持 ISO 代码、中英文名、俚语（刀 / 软妹币 / U）、货币符号、国旗 emoji、
以及常见的口语缩写（rmb / kuai / bucks / quid）。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class Currency:
    code: str
    zh: str
    en: str
    symbol: str = ""
    flag: str = ""
    kind: str = "fiat"  # fiat | crypto | metal
    decimals: int = 2
    aliases: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_crypto(self) -> bool:
        return self.kind == "crypto"

    def label(self, lang: str = "zh") -> str:
        name = self.zh if lang == "zh" else self.en
        return f"{self.flag} {self.code} {name}".strip()

    def short_label(self, lang: str = "zh") -> str:
        return f"{self.flag}{self.code}" if self.flag else self.code


# fmt: off
_FIAT: list[Currency] = [
    Currency("CNY", "人民币", "Chinese Yuan", "¥", "🇨🇳", aliases=("rmb", "yuan", "renminbi", "元", "块", "块钱", "软妹币", "人民幣", "中国", "中國", "国币", "cny", "cnh", "圆")),
    Currency("USD", "美元", "US Dollar", "$", "🇺🇸", aliases=("usd", "dollar", "dollars", "buck", "bucks", "美刀", "刀", "美金", "美圆", "美国", "美國", "米元", "绿钞")),
    Currency("EUR", "欧元", "Euro", "€", "🇪🇺", aliases=("eur", "euro", "euros", "欧", "歐元", "歐", "欧洲")),
    Currency("JPY", "日元", "Japanese Yen", "¥", "🇯🇵", decimals=0, aliases=("jpy", "yen", "日圆", "日圓", "円", "日本", "日币", "日幣", "小钱钱")),
    Currency("HKD", "港币", "Hong Kong Dollar", "HK$", "🇭🇰", aliases=("hkd", "港元", "港幣", "香港", "港纸", "港紙")),
    Currency("GBP", "英镑", "British Pound", "£", "🇬🇧", aliases=("gbp", "pound", "pounds", "sterling", "quid", "英磅", "英鎊", "英国", "英國", "镑")),
    Currency("KRW", "韩元", "South Korean Won", "₩", "🇰🇷", decimals=0, aliases=("krw", "won", "韩币", "韓元", "韓幣", "韩国", "韓國", "韩币")),
    Currency("TWD", "新台币", "New Taiwan Dollar", "NT$", "🇹🇼", aliases=("twd", "ntd", "台币", "台幣", "新臺幣", "台湾", "臺灣", "新台幣")),
    Currency("SGD", "新加坡元", "Singapore Dollar", "S$", "🇸🇬", aliases=("sgd", "新币", "新幣", "坡币", "坡幣", "新加坡", "狮城")),
    Currency("AUD", "澳元", "Australian Dollar", "A$", "🇦🇺", aliases=("aud", "澳币", "澳幣", "澳大利亚", "澳洲", "澳刀")),
    Currency("CAD", "加元", "Canadian Dollar", "C$", "🇨🇦", aliases=("cad", "加币", "加幣", "加拿大", "枫叶")),
    Currency("CHF", "瑞士法郎", "Swiss Franc", "Fr", "🇨🇭", aliases=("chf", "franc", "法郎", "瑞郎", "瑞士")),
    Currency("NZD", "新西兰元", "New Zealand Dollar", "NZ$", "🇳🇿", aliases=("nzd", "纽币", "紐幣", "新西兰", "紐西蘭", "奇异鸟")),
    Currency("THB", "泰铢", "Thai Baht", "฿", "🇹🇭", aliases=("thb", "baht", "泰珠", "泰銖", "泰国", "泰國", "铢")),
    Currency("VND", "越南盾", "Vietnamese Dong", "₫", "🇻🇳", decimals=0, aliases=("vnd", "dong", "越南", "盾")),
    Currency("MYR", "马来西亚林吉特", "Malaysian Ringgit", "RM", "🇲🇾", aliases=("myr", "ringgit", "林吉特", "马币", "馬幣", "马来西亚", "马来")),
    Currency("IDR", "印尼盾", "Indonesian Rupiah", "Rp", "🇮🇩", decimals=0, aliases=("idr", "rupiah", "印尼", "印度尼西亚")),
    Currency("PHP", "菲律宾比索", "Philippine Peso", "₱", "🇵🇭", aliases=("php", "peso", "菲律宾", "菲律賓", "菲币")),
    Currency("INR", "印度卢比", "Indian Rupee", "₹", "🇮🇳", aliases=("inr", "rupee", "卢比", "盧比", "印度")),
    Currency("RUB", "俄罗斯卢布", "Russian Ruble", "₽", "🇷🇺", aliases=("rub", "ruble", "rouble", "卢布", "盧布", "俄罗斯", "俄國", "俄国", "毛子")),
    Currency("BRL", "巴西雷亚尔", "Brazilian Real", "R$", "🇧🇷", aliases=("brl", "real", "雷亚尔", "巴西")),
    Currency("MXN", "墨西哥比索", "Mexican Peso", "Mex$", "🇲🇽", aliases=("mxn", "墨西哥", "墨币")),
    Currency("ZAR", "南非兰特", "South African Rand", "R", "🇿🇦", aliases=("zar", "rand", "兰特", "蘭特", "南非")),
    Currency("TRY", "土耳其里拉", "Turkish Lira", "₺", "🇹🇷", aliases=("try", "lira", "里拉", "土耳其")),
    Currency("AED", "阿联酋迪拉姆", "UAE Dirham", "د.إ", "🇦🇪", aliases=("aed", "dirham", "迪拉姆", "阿联酋", "迪拜", "杜拜")),
    Currency("SAR", "沙特里亚尔", "Saudi Riyal", "﷼", "🇸🇦", aliases=("sar", "riyal", "里亚尔", "沙特", "沙烏地")),
    Currency("SEK", "瑞典克朗", "Swedish Krona", "kr", "🇸🇪", aliases=("sek", "krona", "瑞典", "瑞典克郎")),
    Currency("NOK", "挪威克朗", "Norwegian Krone", "kr", "🇳🇴", aliases=("nok", "挪威")),
    Currency("DKK", "丹麦克朗", "Danish Krone", "kr", "🇩🇰", aliases=("dkk", "丹麦", "丹麥")),
    Currency("PLN", "波兰兹罗提", "Polish Zloty", "zł", "🇵🇱", aliases=("pln", "zloty", "兹罗提", "波兰", "波蘭")),
    Currency("CZK", "捷克克朗", "Czech Koruna", "Kč", "🇨🇿", aliases=("czk", "koruna", "捷克")),
    Currency("HUF", "匈牙利福林", "Hungarian Forint", "Ft", "🇭🇺", decimals=0, aliases=("huf", "forint", "福林", "匈牙利")),
    Currency("ILS", "以色列新谢克尔", "Israeli New Shekel", "₪", "🇮🇱", aliases=("ils", "shekel", "谢克尔", "以色列")),
    Currency("EGP", "埃及镑", "Egyptian Pound", "E£", "🇪🇬", aliases=("egp", "埃及")),
    Currency("NGN", "尼日利亚奈拉", "Nigerian Naira", "₦", "🇳🇬", aliases=("ngn", "naira", "奈拉", "尼日利亚")),
    Currency("KES", "肯尼亚先令", "Kenyan Shilling", "KSh", "🇰🇪", aliases=("kes", "肯尼亚", "先令")),
    Currency("ARS", "阿根廷比索", "Argentine Peso", "$", "🇦🇷", aliases=("ars", "阿根廷")),
    Currency("CLP", "智利比索", "Chilean Peso", "$", "🇨🇱", decimals=0, aliases=("clp", "智利")),
    Currency("COP", "哥伦比亚比索", "Colombian Peso", "$", "🇨🇴", decimals=0, aliases=("cop", "哥伦比亚")),
    Currency("PEN", "秘鲁索尔", "Peruvian Sol", "S/", "🇵🇪", aliases=("pen", "秘鲁", "索尔")),
    Currency("PKR", "巴基斯坦卢比", "Pakistani Rupee", "₨", "🇵🇰", aliases=("pkr", "巴基斯坦")),
    Currency("BDT", "孟加拉塔卡", "Bangladeshi Taka", "৳", "🇧🇩", aliases=("bdt", "taka", "孟加拉")),
    Currency("LKR", "斯里兰卡卢比", "Sri Lankan Rupee", "Rs", "🇱🇰", aliases=("lkr", "斯里兰卡")),
    Currency("NPR", "尼泊尔卢比", "Nepalese Rupee", "₨", "🇳🇵", aliases=("npr", "尼泊尔")),
    Currency("KHR", "柬埔寨瑞尔", "Cambodian Riel", "៛", "🇰🇭", decimals=0, aliases=("khr", "riel", "瑞尔", "柬埔寨")),
    Currency("LAK", "老挝基普", "Lao Kip", "₭", "🇱🇦", decimals=0, aliases=("lak", "kip", "基普", "老挝", "寮國")),
    Currency("MMK", "缅甸元", "Myanmar Kyat", "K", "🇲🇲", decimals=0, aliases=("mmk", "kyat", "缅甸", "緬甸")),
    Currency("MOP", "澳门元", "Macanese Pataca", "MOP$", "🇲🇴", aliases=("mop", "澳门币", "澳門幣", "澳门", "澳門", "葡币")),
    Currency("MNT", "蒙古图格里克", "Mongolian Tugrik", "₮", "🇲🇳", decimals=0, aliases=("mnt", "蒙古")),
    Currency("KZT", "哈萨克坚戈", "Kazakhstani Tenge", "₸", "🇰🇿", aliases=("kzt", "tenge", "哈萨克")),
    Currency("UZS", "乌兹别克苏姆", "Uzbekistani Som", "so'm", "🇺🇿", decimals=0, aliases=("uzs", "乌兹别克")),
    Currency("UAH", "乌克兰格里夫纳", "Ukrainian Hryvnia", "₴", "🇺🇦", aliases=("uah", "hryvnia", "乌克兰", "烏克蘭")),
    Currency("RON", "罗马尼亚列伊", "Romanian Leu", "lei", "🇷🇴", aliases=("ron", "leu", "罗马尼亚")),
    Currency("BGN", "保加利亚列弗", "Bulgarian Lev", "лв", "🇧🇬", aliases=("bgn", "lev", "保加利亚")),
    Currency("HRK", "克罗地亚库纳", "Croatian Kuna", "kn", "🇭🇷", aliases=("hrk", "克罗地亚")),
    Currency("ISK", "冰岛克朗", "Icelandic Krona", "kr", "🇮🇸", decimals=0, aliases=("isk", "冰岛", "冰島")),
    Currency("QAR", "卡塔尔里亚尔", "Qatari Riyal", "﷼", "🇶🇦", aliases=("qar", "卡塔尔")),
    Currency("KWD", "科威特第纳尔", "Kuwaiti Dinar", "د.ك", "🇰🇼", decimals=3, aliases=("kwd", "dinar", "科威特")),
    Currency("BHD", "巴林第纳尔", "Bahraini Dinar", ".د.ب", "🇧🇭", decimals=3, aliases=("bhd", "巴林")),
    Currency("OMR", "阿曼里亚尔", "Omani Rial", "﷼", "🇴🇲", decimals=3, aliases=("omr", "阿曼")),
    Currency("JOD", "约旦第纳尔", "Jordanian Dinar", "د.ا", "🇯🇴", decimals=3, aliases=("jod", "约旦")),
    Currency("MAD", "摩洛哥迪拉姆", "Moroccan Dirham", "د.م.", "🇲🇦", aliases=("mad", "摩洛哥")),
    Currency("TND", "突尼斯第纳尔", "Tunisian Dinar", "د.ت", "🇹🇳", decimals=3, aliases=("tnd", "突尼斯")),
    Currency("DZD", "阿尔及利亚第纳尔", "Algerian Dinar", "د.ج", "🇩🇿", aliases=("dzd", "阿尔及利亚")),
    Currency("ETB", "埃塞俄比亚比尔", "Ethiopian Birr", "Br", "🇪🇹", aliases=("etb", "埃塞俄比亚")),
    Currency("GHS", "加纳塞地", "Ghanaian Cedi", "₵", "🇬🇭", aliases=("ghs", "加纳")),
    Currency("TZS", "坦桑尼亚先令", "Tanzanian Shilling", "TSh", "🇹🇿", decimals=0, aliases=("tzs", "坦桑尼亚")),
    Currency("UGX", "乌干达先令", "Ugandan Shilling", "USh", "🇺🇬", decimals=0, aliases=("ugx", "乌干达")),
    Currency("XAF", "中非法郎", "Central African CFA Franc", "FCFA", "🌍", decimals=0, aliases=("xaf", "中非法郎")),
    Currency("XOF", "西非法郎", "West African CFA Franc", "CFA", "🌍", decimals=0, aliases=("xof", "西非法郎")),
    Currency("FJD", "斐济元", "Fijian Dollar", "FJ$", "🇫🇯", aliases=("fjd", "斐济")),
    Currency("PGK", "巴布亚新几内亚基那", "Papua New Guinean Kina", "K", "🇵🇬", aliases=("pgk",)),
    Currency("BND", "文莱元", "Brunei Dollar", "B$", "🇧🇳", aliases=("bnd", "文莱", "汶萊")),
    Currency("MVR", "马尔代夫拉菲亚", "Maldivian Rufiyaa", "Rf", "🇲🇻", aliases=("mvr", "马尔代夫")),
    Currency("AZN", "阿塞拜疆马纳特", "Azerbaijani Manat", "₼", "🇦🇿", aliases=("azn", "阿塞拜疆")),
    Currency("GEL", "格鲁吉亚拉里", "Georgian Lari", "₾", "🇬🇪", aliases=("gel", "格鲁吉亚")),
    Currency("AMD", "亚美尼亚德拉姆", "Armenian Dram", "֏", "🇦🇲", decimals=0, aliases=("amd", "亚美尼亚")),
    Currency("BYN", "白俄罗斯卢布", "Belarusian Ruble", "Br", "🇧🇾", aliases=("byn", "白俄罗斯", "白俄")),
    Currency("RSD", "塞尔维亚第纳尔", "Serbian Dinar", "дин", "🇷🇸", aliases=("rsd", "塞尔维亚")),
    Currency("IRR", "伊朗里亚尔", "Iranian Rial", "﷼", "🇮🇷", decimals=0, aliases=("irr", "伊朗")),
    Currency("IQD", "伊拉克第纳尔", "Iraqi Dinar", "ع.د", "🇮🇶", decimals=3, aliases=("iqd", "伊拉克")),
    Currency("LBP", "黎巴嫩镑", "Lebanese Pound", "ل.ل", "🇱🇧", decimals=0, aliases=("lbp", "黎巴嫩")),
    Currency("VES", "委内瑞拉玻利瓦尔", "Venezuelan Bolívar", "Bs.", "🇻🇪", aliases=("ves", "vef", "委内瑞拉")),
    Currency("UYU", "乌拉圭比索", "Uruguayan Peso", "$U", "🇺🇾", aliases=("uyu", "乌拉圭")),
    Currency("BOB", "玻利维亚诺", "Bolivian Boliviano", "Bs.", "🇧🇴", aliases=("bob", "玻利维亚")),
    Currency("PYG", "巴拉圭瓜拉尼", "Paraguayan Guarani", "₲", "🇵🇾", decimals=0, aliases=("pyg", "巴拉圭")),
    Currency("CRC", "哥斯达黎加科朗", "Costa Rican Colon", "₡", "🇨🇷", aliases=("crc", "哥斯达黎加")),
    Currency("DOP", "多米尼加比索", "Dominican Peso", "RD$", "🇩🇴", aliases=("dop", "多米尼加")),
    Currency("GTQ", "危地马拉格查尔", "Guatemalan Quetzal", "Q", "🇬🇹", aliases=("gtq", "危地马拉")),
    Currency("JMD", "牙买加元", "Jamaican Dollar", "J$", "🇯🇲", aliases=("jmd", "牙买加")),
    Currency("TTD", "特立尼达元", "Trinidad Dollar", "TT$", "🇹🇹", aliases=("ttd", "特立尼达")),
    Currency("BSD", "巴哈马元", "Bahamian Dollar", "B$", "🇧🇸", aliases=("bsd", "巴哈马")),
    Currency("BBD", "巴巴多斯元", "Barbadian Dollar", "Bds$", "🇧🇧", aliases=("bbd", "巴巴多斯")),
    Currency("XCD", "东加勒比元", "East Caribbean Dollar", "EC$", "🌎", aliases=("xcd",)),
    Currency("BMD", "百慕大元", "Bermudian Dollar", "BD$", "🇧🇲", aliases=("bmd", "百慕大")),
    Currency("KYD", "开曼元", "Cayman Islands Dollar", "CI$", "🇰🇾", aliases=("kyd", "开曼")),
    Currency("MUR", "毛里求斯卢比", "Mauritian Rupee", "₨", "🇲🇺", aliases=("mur", "毛里求斯")),
    Currency("MDL", "摩尔多瓦列伊", "Moldovan Leu", "L", "🇲🇩", aliases=("mdl", "摩尔多瓦")),
    Currency("ALL", "阿尔巴尼亚列克", "Albanian Lek", "L", "🇦🇱", aliases=("all", "阿尔巴尼亚")),
    Currency("MKD", "北马其顿代纳尔", "Macedonian Denar", "ден", "🇲🇰", aliases=("mkd", "马其顿")),
    Currency("BAM", "波黑可兑换马克", "Bosnia Mark", "KM", "🇧🇦", aliases=("bam", "波黑")),
    Currency("AFN", "阿富汗尼", "Afghan Afghani", "؋", "🇦🇫", aliases=("afn", "阿富汗")),
    Currency("SYP", "叙利亚镑", "Syrian Pound", "£S", "🇸🇾", decimals=0, aliases=("syp", "叙利亚")),
    Currency("YER", "也门里亚尔", "Yemeni Rial", "﷼", "🇾🇪", decimals=0, aliases=("yer", "也门")),
    Currency("SDG", "苏丹镑", "Sudanese Pound", "ج.س", "🇸🇩", aliases=("sdg", "苏丹")),
    Currency("AOA", "安哥拉宽扎", "Angolan Kwanza", "Kz", "🇦🇴", aliases=("aoa", "安哥拉")),
    Currency("MZN", "莫桑比克梅蒂卡尔", "Mozambican Metical", "MT", "🇲🇿", aliases=("mzn", "莫桑比克")),
    Currency("ZMW", "赞比亚克瓦查", "Zambian Kwacha", "ZK", "🇿🇲", aliases=("zmw", "赞比亚")),
    Currency("BWP", "博茨瓦纳普拉", "Botswana Pula", "P", "🇧🇼", aliases=("bwp", "博茨瓦纳")),
    Currency("NAD", "纳米比亚元", "Namibian Dollar", "N$", "🇳🇦", aliases=("nad", "纳米比亚")),
]

_METAL: list[Currency] = [
    Currency("XAU", "黄金(盎司)", "Gold (oz)", "", "🥇", kind="metal", decimals=4, aliases=("xau", "gold", "黄金", "金价", "金")),
    Currency("XAG", "白银(盎司)", "Silver (oz)", "", "🥈", kind="metal", decimals=4, aliases=("xag", "silver", "白银", "银价", "银")),
    Currency("XPT", "铂金(盎司)", "Platinum (oz)", "", "⚪", kind="metal", decimals=4, aliases=("xpt", "platinum", "铂金")),
]

_CRYPTO: list[Currency] = [
    Currency("BTC", "比特币", "Bitcoin", "₿", "🟠", kind="crypto", decimals=8, aliases=("btc", "bitcoin", "比特币", "大饼", "xbt")),
    Currency("ETH", "以太坊", "Ethereum", "Ξ", "🔷", kind="crypto", decimals=6, aliases=("eth", "ethereum", "以太坊", "以太", "姨太")),
    Currency("USDT", "泰达币", "Tether", "₮", "🟢", kind="crypto", decimals=4, aliases=("usdt", "tether", "泰达", "u", "稳定币")),
    Currency("USDC", "USD Coin", "USD Coin", "", "🔵", kind="crypto", decimals=4, aliases=("usdc",)),
    Currency("BNB", "币安币", "BNB", "", "🟡", kind="crypto", decimals=6, aliases=("bnb", "币安币", "币安")),
    Currency("SOL", "Solana", "Solana", "", "🟣", kind="crypto", decimals=6, aliases=("sol", "solana", "索拉纳")),
    Currency("XRP", "瑞波币", "XRP", "", "⚫", kind="crypto", decimals=6, aliases=("xrp", "ripple", "瑞波")),
    Currency("DOGE", "狗狗币", "Dogecoin", "", "🐕", kind="crypto", decimals=6, aliases=("doge", "dogecoin", "狗狗币", "狗币")),
    Currency("ADA", "艾达币", "Cardano", "", "🔵", kind="crypto", decimals=6, aliases=("ada", "cardano", "艾达")),
    Currency("TRX", "波场", "TRON", "", "🔴", kind="crypto", decimals=6, aliases=("trx", "tron", "波场", "孙割")),
    Currency("TON", "TON", "Toncoin", "", "💎", kind="crypto", decimals=6, aliases=("ton", "toncoin")),
    Currency("AVAX", "雪崩", "Avalanche", "", "🔺", kind="crypto", decimals=6, aliases=("avax", "avalanche")),
    Currency("DOT", "波卡", "Polkadot", "", "🟤", kind="crypto", decimals=6, aliases=("dot", "polkadot", "波卡")),
    Currency("MATIC", "Polygon", "Polygon", "", "🟪", kind="crypto", decimals=6, aliases=("matic", "polygon")),
    Currency("LTC", "莱特币", "Litecoin", "Ł", "⚪", kind="crypto", decimals=6, aliases=("ltc", "litecoin", "莱特币", "莱特")),
    Currency("BCH", "比特现金", "Bitcoin Cash", "", "🟩", kind="crypto", decimals=6, aliases=("bch", "比特现金", "bcash")),
    Currency("LINK", "Chainlink", "Chainlink", "", "🔗", kind="crypto", decimals=6, aliases=("link", "chainlink", "预言机")),
    Currency("SHIB", "柴犬币", "Shiba Inu", "", "🐕", kind="crypto", decimals=8, aliases=("shib", "shiba", "柴犬")),
    Currency("UNI", "Uniswap", "Uniswap", "", "🦄", kind="crypto", decimals=6, aliases=("uni", "uniswap")),
    Currency("ATOM", "Cosmos", "Cosmos", "", "⚛️", kind="crypto", decimals=6, aliases=("atom", "cosmos")),
    Currency("XLM", "恒星币", "Stellar", "", "✨", kind="crypto", decimals=6, aliases=("xlm", "stellar", "恒星")),
    Currency("ETC", "以太经典", "Ethereum Classic", "", "🟩", kind="crypto", decimals=6, aliases=("etc", "以太经典")),
    Currency("FIL", "Filecoin", "Filecoin", "", "🗄️", kind="crypto", decimals=6, aliases=("fil", "filecoin")),
    Currency("APT", "Aptos", "Aptos", "", "⬛", kind="crypto", decimals=6, aliases=("apt", "aptos")),
    Currency("ARB", "Arbitrum", "Arbitrum", "", "🔷", kind="crypto", decimals=6, aliases=("arb", "arbitrum")),
    Currency("OP", "Optimism", "Optimism", "", "🔴", kind="crypto", decimals=6, aliases=("op", "optimism")),
    Currency("NEAR", "NEAR", "NEAR Protocol", "", "⬜", kind="crypto", decimals=6, aliases=("near",)),
    Currency("SUI", "Sui", "Sui", "", "💧", kind="crypto", decimals=6, aliases=("sui",)),
    Currency("PEPE", "Pepe", "Pepe", "", "🐸", kind="crypto", decimals=10, aliases=("pepe",)),
    Currency("DAI", "Dai", "Dai", "", "🟨", kind="crypto", decimals=4, aliases=("dai",)),
]
# fmt: on

ALL_CURRENCIES: dict[str, Currency] = {c.code: c for c in (_FIAT + _METAL + _CRYPTO)}

FIAT_CODES: frozenset[str] = frozenset(c.code for c in _FIAT)
METAL_CODES: frozenset[str] = frozenset(c.code for c in _METAL)
CRYPTO_CODES: frozenset[str] = frozenset(c.code for c in _CRYPTO)

# 主流货币，用于快捷键盘 / 空查询建议
POPULAR: tuple[str, ...] = ("CNY", "USD", "EUR", "JPY", "HKD", "GBP", "KRW", "TWD", "SGD", "AUD", "CAD", "THB")

# 常用列表不够长时，按这个顺序补齐，保证一次总能看到足够多的行
FILLER: tuple[str, ...] = (
    "USD", "HKD", "EUR", "JPY", "GBP", "KRW", "TWD", "SGD", "AUD", "CAD",
    "THB", "CHF", "NZD", "MYR", "PHP", "VND", "RUB", "INR", "MOP", "IDR",
)

# 「常用币种」选择面板的候选池（分页展示）
PICKER_POOL: tuple[str, ...] = (
    # 亚太
    "USD", "CNY", "HKD", "JPY", "KRW", "TWD", "SGD", "MOP", "THB", "MYR",
    "PHP", "VND", "IDR", "INR", "AUD", "NZD", "KHR", "LAK", "MMK", "BDT",
    # 欧美中东
    "EUR", "GBP", "CHF", "CAD", "RUB", "SEK", "NOK", "DKK", "PLN", "CZK",
    "TRY", "AED", "SAR", "ILS", "UAH", "HUF", "RON", "KZT", "BRL", "MXN",
    "ZAR", "ARS", "EGP", "NGN",
    # 加密与贵金属
    "USDT", "USDC", "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "TRX", "TON",
    "XAU", "XAG",
)

# 符号 → 候选货币（顺序即优先级）。¥ / $ 天然有歧义，交给上下文消歧。
SYMBOL_MAP: dict[str, tuple[str, ...]] = {
    "$": ("USD", "HKD", "TWD", "SGD", "AUD", "CAD"),
    "＄": ("USD",),
    "¥": ("CNY", "JPY"),
    "￥": ("CNY", "JPY"),
    "€": ("EUR",),
    "£": ("GBP",),
    "₩": ("KRW",),
    "₹": ("INR",),
    "₽": ("RUB",),
    "฿": ("THB",),
    "₫": ("VND",),
    "₱": ("PHP",),
    "₺": ("TRY",),
    "₪": ("ILS",),
    "₦": ("NGN",),
    "₴": ("UAH",),
    "₸": ("KZT",),
    "₮": ("MNT", "USDT"),
    "₿": ("BTC",),
    "Ξ": ("ETH",),
    "元": ("CNY",),
    "円": ("JPY",),
    "圓": ("JPY",),
}

# 国旗 emoji → 货币
FLAG_MAP: dict[str, str] = {}
for _c in ALL_CURRENCIES.values():
    if _c.flag and _c.flag not in FLAG_MAP and len(_c.flag) >= 2:
        FLAG_MAP.setdefault(_c.flag, _c.code)


def _normalize(token: str) -> str:
    """统一大小写 / 全角半角 / 去掉装饰字符。"""
    token = unicodedata.normalize("NFKC", token).strip()
    token = token.replace("﻿", "").replace("​", "")
    return token.lower()


def _build_alias_index() -> dict[str, str]:
    index: dict[str, str] = {}

    def put(key: str, code: str, *, weak: bool = False) -> None:
        key = _normalize(key)
        if not key:
            return
        if key in index and index[key] != code:
            # 已有映射时，非弱绑定可以覆盖弱绑定；否则先到先得
            if weak:
                return
        index[key] = code

    for cur in ALL_CURRENCIES.values():
        put(cur.code, cur.code)
        put(cur.zh, cur.code)
        put(cur.en, cur.code)
        for alias in cur.aliases:
            put(alias, cur.code)

    # 常见后缀写法：人民币/日元 已在别名内；这里补充「XX币」「XX元」的组合
    for cur in _FIAT:
        base = cur.zh
        for suffix in ("币", "幣", "元"):
            if not base.endswith(suffix):
                put(base + suffix, cur.code, weak=True)
    return index


ALIAS_INDEX: dict[str, str] = _build_alias_index()

# 别名里最长的中文词，供分词时贪婪匹配使用
_ALIAS_KEYS_BY_LEN: list[str] = sorted(ALIAS_INDEX.keys(), key=len, reverse=True)
_CJK_ALIAS_KEYS: list[str] = [k for k in _ALIAS_KEYS_BY_LEN if re.search(r"[一-鿿]", k)]


def resolve(token: str, *, context: str | None = None) -> Currency | None:
    """把任意用户输入片段解析为货币。

    context 用于符号消歧：例如用户默认币种是 JPY 时，`¥` 优先解析为 JPY。
    """
    if not token:
        return None
    key = _normalize(token)

    if key in ALIAS_INDEX:
        return ALL_CURRENCIES[ALIAS_INDEX[key]]

    raw = unicodedata.normalize("NFKC", token).strip()
    if raw in SYMBOL_MAP:
        candidates = SYMBOL_MAP[raw]
        if context and context.upper() in candidates:
            return ALL_CURRENCIES[context.upper()]
        return ALL_CURRENCIES[candidates[0]]

    if token.strip() in FLAG_MAP:
        return ALL_CURRENCIES[FLAG_MAP[token.strip()]]

    # 去掉常见量词/助词后再试一次：「美元的」「日元啊」
    stripped = re.sub(r"[的了吗呢啊呀吧么嘛?？!！,，。\s]+$", "", key)
    if stripped != key and stripped in ALIAS_INDEX:
        return ALL_CURRENCIES[ALIAS_INDEX[stripped]]

    return None


def resolve_code(token: str, *, context: str | None = None) -> str | None:
    cur = resolve(token, context=context)
    return cur.code if cur else None


def get(code: str) -> Currency:
    """取货币元数据；未知代码返回一个占位对象，避免上层到处判空。"""
    code = code.upper()
    if code in ALL_CURRENCIES:
        return ALL_CURRENCIES[code]
    return Currency(code, code, code)


def is_known(code: str) -> bool:
    return code.upper() in ALL_CURRENCIES


def search(query: str, limit: int = 20) -> list[Currency]:
    """模糊搜索货币：代码前缀 > 名称包含 > 别名包含。"""
    q = _normalize(query)
    if not q:
        return [ALL_CURRENCIES[c] for c in POPULAR]

    exact: list[Currency] = []
    prefix: list[Currency] = []
    contains: list[Currency] = []
    for cur in ALL_CURRENCIES.values():
        code = cur.code.lower()
        haystack = f"{code} {_normalize(cur.zh)} {_normalize(cur.en)} {' '.join(cur.aliases)}"
        if code == q or q in {_normalize(cur.zh), _normalize(cur.en)}:
            exact.append(cur)
        elif code.startswith(q) or _normalize(cur.zh).startswith(q) or _normalize(cur.en).startswith(q):
            prefix.append(cur)
        elif q in haystack:
            contains.append(cur)
    return (exact + prefix + contains)[:limit]


def cjk_alias_pattern() -> list[str]:
    """返回按长度倒序的中文别名列表，供解析器做最长匹配。"""
    return _CJK_ALIAS_KEYS
