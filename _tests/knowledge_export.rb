# Run with Jekyll 3.9.5 and the site's plugins installed. No website writes.
require 'jekyll'
require 'json'
require 'tmpdir'
require 'fileutils'
require 'digest'

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
check(content['documents'].size == expected.size, 'Published inventory is incomplete')
check(manifest['counts'] == content['counts'], 'Counts differ')
check(manifest['exported_at'] == content['exported_at'], 'Build times differ')
check(manifest['build_revision'] == REVISION, 'Local revision binding missing')
check(manifest['document_ids'].sort == content['documents'].map { |d| d['id'] }.sort, 'Inventory differs')
check(manifest['document_ids'].uniq.size == expected.size, 'Duplicate canonical URLs')
expected.each do |doc|
  row = content['documents'].find { |d| d['canonical_url'] == site.config['url'] + doc.url }
  check(!row.nil?, "Missing #{doc.url}")
  check(row['content_html'] == doc.content, "Truncated/changed body: #{doc.url}")
  check(!row['content_html'].match?(/\{%|\{\{/), "Unrendered Liquid: #{doc.url}")
  check(row['collection'] == doc.collection.label, "Wrong collection: #{doc.url}")
end
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
  _, m1, c1 = render(dir, 'future' => true, 'unpublished' => true, 'show_drafts' => true)
  check(c1['documents'].size == 1, 'Preview exposes nonpublic documents')
  check(c1['documents'].first['content_html'].include?('END-OF-ARTICLE'), 'Long article truncated')
  check(c1['documents'].first['content_html'].include?('日本語'), 'Unicode lost')
  check(!JSON.generate(c1).match?(/PRIVATE-SENTINEL|FUTURE-SENTINEL|FUTURE-COLLECTION|HIDDEN-SENTINEL|DRAFT-SENTINEL/), 'Nonpublic leak')
  path = File.join(dir, '_posts/2020-01-01-public.md')
  File.write(path, File.read(path) + '\nCORRECTION-END')
  _, _, c2 = render(dir)
  check(c2['documents'].first['content_html'].include?('CORRECTION-END'), 'Modification not exported')
  check(c1['documents'].first['id'] == c2['documents'].first['id'], 'Identity changed on edit')
  File.delete(path)
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
