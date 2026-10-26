# Run with Jekyll 3.9.5 and the site's plugins installed. No website writes.
require 'jekyll'
require 'json'
require 'tmpdir'
require 'fileutils'
require 'digest'
require 'cgi'

ROOT = File.expand_path('..', __dir__)
REVISION = 'a' * 40
$checks = 0
def check(condition, message)
  raise message unless condition
  $checks += 1
end

def render(source, extra = {})
  source = File.realpath(source) # macOS /var is a symlink; safe-mode includes require real paths.
  config = Jekyll.configuration({'source' => source, 'destination' => '/tmp/iris-studio-unused-output',
    'quiet' => true, 'strict_front_matter' => true, 'safe' => true,
    'whitelist' => ['jekyll-paginate', 'jekyll-sitemap'],
    'knowledge_revision' => REVISION, 'incremental' => false}.merge(extra))
  site = Jekyll::Site.new(config)
  # Identical read/generate/render path to a build, without copying media files.
  site.reset; site.read; site.generate; site.render
  pages = site.pages.to_h { |page| [page.url, page.output] }
  [site, JSON.parse(pages.fetch('/knowledge/manifest.json')), JSON.parse(pages.fetch('/knowledge/content.json'))]
end

site, manifest, content = render(ROOT)
expected = site.collections.values.select { |c| c.metadata['output'] }.flat_map(&:docs).select do |doc|
  doc.data['published'] != false && doc.date <= site.time && !doc.path.include?('/_drafts/')
end
standalone = site.pages.select { |page| page.data['knowledge'] == true }
expected += standalone
check(content['documents'].size == expected.size, "Published inventory is incomplete: #{content['documents'].size}/#{expected.size}")
check(manifest['counts'] == content['counts'], 'Counts differ')
check(manifest['exported_at'] == content['exported_at'], 'Build times differ')
check(manifest['build_revision'] == REVISION, 'Local revision binding missing')
check(manifest['document_ids'].sort == content['documents'].map { |d| d['id'] }.sort, 'Inventory differs')
check(manifest['document_ids'].uniq.size == expected.size, 'Duplicate canonical URLs')
expected.each do |doc|
  row = content['documents'].find { |d| d['canonical_url'] == site.config['url'] + doc.url }
  check(!row.nil?, "Missing #{doc.url}")
  body = doc.is_a?(Jekyll::Page) ? site.find_converter_instance(Jekyll::Converters::Markdown).convert(doc.content) : doc.content
  if doc.is_a?(Jekyll::Page)
    header = %w[eyebrow dates venue].filter_map { |field| doc.data[field] && "<p>#{CGI.escapeHTML(doc.data[field])}</p>" }.join
    body = header + body
  end
  check(row['content_html'] == body, "Truncated/changed body: #{doc.url}")
  check(!row['content_html'].match?(/\{%|\{\{/), "Unrendered Liquid: #{doc.url}")
  collection = doc.is_a?(Jekyll::Page) ? 'pages' : doc.collection.label
  check(row['collection'] == collection, "Wrong collection: #{doc.url}")
end
event_paths = ['', 'en/', 'ja/', 'de/', 'fr/'].map { |prefix| "/#{prefix}deep-in-memory/" }
check(standalone.map(&:url).sort == event_paths.sort, 'Standalone inventory must contain only the five editorial event pages')
event_paths.each do |path|
  row = content['documents'].find { |doc| doc['canonical_url'] == site.config['url'] + path }
  page = standalone.find { |doc| doc.url == path }
  check(!row.nil? && manifest['document_ids'].include?(row['canonical_url']), "Missing Paris event: #{path}")
  check(page.data['eyebrow'].match?(/2025|二〇二五/), "Wrong event edition: #{path}")
  header = %w[eyebrow dates venue].map { |field| "<p>#{CGI.escapeHTML(page.data.fetch(field))}</p>" }.join
  check(row['content_html'].start_with?(header), "Visible event header omitted or changed: #{path}")
  check(row['content_html'].include?(page.content.lines.reject { |line| line.strip.empty? }.last.strip), "Event body ending missing: #{path}")
  check(!row['content_html'].include?('deep-in-memory__'), "Layout chrome exported: #{path}")
end
check(!manifest['document_ids'].include?(site.config['url'] + '/'), 'Root homepage included as an editorial page')
check(!manifest['document_ids'].include?(site.config['url'] + '/archive/'), 'Archive navigation included as an editorial page')
check(content['documents'].map { |d| d['language'] }.uniq.sort == %w[de en fr ja zh-Hant], 'Missing language')
check(content['attachments'].all? { |a| a['text_extracted'] == false && a['kind'] == 'pdf' }, 'False PDF completion')
check(content['attachments'].size == Dir.glob(File.join(ROOT, 'pdf', '*.pdf')).size, 'Missing PDF inventory')

Dir.mktmpdir('iris-export-test') do |dir|
  %w[_includes knowledge].each { |name| FileUtils.cp_r(File.join(ROOT, name), dir) }
  FileUtils.mkdir_p(File.join(dir, '_posts'))
  FileUtils.mkdir_p(File.join(dir, '_hidden'))
  FileUtils.mkdir_p(File.join(dir, '_en'))
  FileUtils.mkdir_p(File.join(dir, '_drafts'))
  File.write(File.join(dir, '_config.yml'), <<~YAML)
    url: https://www.irischanglabs.com
    collections:
      hidden:
        output: false
      en:
        output: true
    defaults:
      - scope: {path: ''}
        values: {lang: zh}
  YAML
  body = ('完整全文 "quoted" & multilingual 日本語. ' * 400) + ' END-OF-ARTICLE'
  File.write(File.join(dir, '_posts/2020-01-01-public.md'), "---\ntitle: Public\nlayout: post\n---\n#{body}")
  File.write(File.join(dir, '_posts/2020-01-02-private.md'), "---\ntitle: Private\npublished: false\n---\nPRIVATE-SENTINEL")
  File.write(File.join(dir, '_posts/2099-01-01-future.md'), "---\ntitle: Future\n---\nFUTURE-SENTINEL")
  File.write(File.join(dir, '_en/future.md'), "---\ntitle: Future collection\ndate: 2099-01-01\n---\nFUTURE-COLLECTION")
  File.write(File.join(dir, '_hidden/secret.md'), "---\ntitle: Hidden\n---\nHIDDEN-SENTINEL")
  File.write(File.join(dir, '_drafts/draft.md'), "---\ntitle: Draft\n---\nDRAFT-SENTINEL")
  standalone_path = File.join(dir, 'zzz-editorial.md')
  File.write(standalone_path, "---\ntitle: Editorial\nknowledge: true\npermalink: /editorial/\neyebrow: 'Public <event> & programme'\ndates: '21-23 November 2025'\nvenue: 'Theatre \"A\" & B'\n---\nStandalone **editorial**. #{body} END-OF-STANDALONE")
  File.write(File.join(dir, 'navigation.md'), "---\ntitle: Navigation\n---\nNAVIGATION-SENTINEL")
  File.write(File.join(dir, 'private.md'), "---\ntitle: Private page\nknowledge: true\npublished: false\n---\nPRIVATE-PAGE-SENTINEL")
  File.write(File.join(dir, 'future.md'), "---\ntitle: Future page\nknowledge: true\ndate: 2099-01-01\n---\nFUTURE-PAGE-SENTINEL")
  _, m1, c1 = render(dir, 'future' => true, 'unpublished' => true, 'show_drafts' => true)
  check(c1['documents'].size == 2, 'Preview exposes nonpublic documents or misses eligible pages')
  standalone_row = c1['documents'].find { |doc| doc['canonical_url'].end_with?('/editorial/') }
  check(standalone_row['collection'] == 'pages', 'Standalone collection fallback missing')
  check(standalone_row['content_html'].start_with?('<p>Public &lt;event&gt; &amp; programme</p><p>21-23 November 2025</p><p>Theatre &quot;A&quot; &amp; B</p>'), 'Visible event headers must be complete and escaped')
  check(standalone_row['content_html'].include?('<strong>editorial</strong>') && standalone_row['content_html'].include?('END-OF-STANDALONE'), 'Late-rendered standalone body is not complete HTML')
  check(c1['documents'].first['content_html'].include?('END-OF-ARTICLE'), 'Long article truncated')
  check(c1['documents'].first['content_html'].include?('日本語'), 'Unicode lost')
  check(!JSON.generate(c1).match?(/PRIVATE-SENTINEL|FUTURE-SENTINEL|FUTURE-COLLECTION|HIDDEN-SENTINEL|DRAFT-SENTINEL|NAVIGATION-SENTINEL|PRIVATE-PAGE-SENTINEL|FUTURE-PAGE-SENTINEL/), 'Nonpublic or navigation leak')
  path = File.join(dir, '_posts/2020-01-01-public.md')
  File.write(path, File.read(path) + '\nCORRECTION-END')
  _, _, c2 = render(dir)
  check(c2['documents'].first['content_html'].include?('CORRECTION-END'), 'Modification not exported')
  check(c1['documents'].first['id'] == c2['documents'].first['id'], 'Identity changed on edit')
  File.delete(path)
  File.delete(standalone_path)
  _, m3, c3 = render(dir)
  check(m3['document_ids'].empty? && c3['documents'].empty?, 'Withdrawal retained in active export')
end

output = ENV['KNOWLEDGE_TEST_OUTPUT']
if output
  FileUtils.mkdir_p(output)
  File.write(File.join(output, 'manifest.json'), JSON.generate(manifest))
  File.write(File.join(output, 'content.json'), JSON.generate(content))
end
puts JSON.generate({result: 'PASS', checks: $checks, documents: expected.size,
  languages: content['documents'].group_by { |d| d['language'] }.transform_values(&:size),
  pdf_attachments: content['attachments'].size, content_bytes: JSON.generate(content).bytesize,
  content_sha256: Digest::SHA256.hexdigest(JSON.generate(content))})
