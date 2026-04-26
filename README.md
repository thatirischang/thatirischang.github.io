# 張純如工作室 · Iris Chang Studio

> 文字是保存靈魂精華的唯一方式。

張純如工作室(Iris Chang Studio)創建於 2018 年 10 月 26 日,由劉羽先生創辦,蒙張純如之父母及其丈夫首肯。工作室致力於翻譯、整理並弘揚張純如女士之演講視頻與文稿,使其精神得以永續傳承。

2022 年 9 月 22 日,工作室於英國正式註冊。

- 官網:<https://www.irischanglabs.com>
- 張純如AI:<https://ai.irischanglabs.com>
- Twitter / X:<https://x.com/irischangstudio>
- YouTube:<https://www.youtube.com/@irischangstudio>

---

## 此倉庫

GitHub Pages 站源碼,基於 Jekyll(Danto 主題)構建,部署目標域名 `www.irischanglabs.com`。
默認分支 `master`,推送即觸發 GitHub Pages 自動部署。

## 站點結構

```
_config.yml             Jekyll 主配置
_data/settings.yml      站點文案、菜單、Hero、Footer、社交鏈接
_data/i18n.yml          多語言 chrome 字符串(EN/日本語/Deutsch/Français/繁中)
_includes/              模板片段(header, footer, hero, ...)
_layouts/               頁面佈局(default, page, post, ...)
_pages/                 獨立頁面(about, videos, authors, tags, featured)
_posts/                 繁中文章(31 篇,2004 - 2025)
_en/ _ja/ _de/ _fr/     四語言子站(各語對應一位母語作家筆法)
images/                 圖片資源
pdf/                    PDF 文檔
CNAME                   自定義域名
```

## 多語言設計

工作室主站為繁體中文。為使張純如女士之精神跨越語種,網站另設四個母語版本,每一版本皆以一位該語種文學大師之筆法、邏輯、母語表達重寫:

| 語言 | 路徑 | 文學聲音 |
|------|------|----------|
| English | `/en/` | Iris Chang 本人(*The Rape of Nanking* 之筆) |
| 日本語 | `/ja/` | 大江健三郎 |
| Deutsch | `/de/` | Stefan Zweig(*Die Welt von Gestern* 之筆) |
| Français | `/fr/` | Marguerite Yourcenar(*Mémoires d'Hadrien* 之筆) |

各語版本內容忠實於繁中原文之事實與結構,差異在於語言、文筆、邏輯展開方式,以求母語讀者讀來如該作家本人執筆。

## 本地開發

```bash
# 一次性安裝(需先安裝 Ruby 3.1+ 與 Bundler)
bundle install

# 啟動本地預覽
bundle exec jekyll serve
# 訪問 http://localhost:4000/
```

## 貢獻

工作室歡迎翻譯校對、史料補充、技術改進。請通過上述官方渠道聯繫。

## 致謝

- 主題:[Danto](https://jekyllthemes.io/theme/danto-jekyll) by Artem Sheludko
- 託管:[GitHub Pages](https://pages.github.com/)
- 字體:Google Fonts
- Iconography:[Ionicons](https://ionicons.com/)
