require 'yaml'

BASE_DIR="masahikosawada.github.io"
UTIL_DIR="utils"
FORMATTER_LINE = "---\n"
TAGPAGE_TEMPLATE = "---
layout: tagpage
title: \"###\"
tag: ###
---
"

$tags_in_posts = []

def get_tags(file)
  in_formatter = false
  formatter = ""

  file.each_line do |line|

    # Find font-formatter area
    if line == FORMATTER_LINE then

      # Found the end of font-formatter.
      # Convert the collected string to yml instance.
      if in_formatter then
        yml = YAML.load(formatter)

        if yml["tags"].nil? then
          p "title \"%s\" does not have any tags" % [yml["title"]]
          exit
        end

        $tags_in_posts.concat(yml["tags"])
        return
      end

      in_formatter = true
      next
    end

    if in_formatter then
      formatter += line
    end
  end
end

# Generate tag page with given name
def generate_tagpage(tagname)
  begin
    File.open("../tag/" + tagname + ".md", "w") do |file|
      tagpage_formatter = TAGPAGE_TEMPLATE.gsub(/###/, tagname)
      file.puts(tagpage_formatter)
    end
  rescue
  end
  puts "generated a tag page for \"%s\"" % [tagname]
end

# Check where we're executing at
pwd = Dir.pwd.split('/')
current_dir = pwd[pwd.length - 1]
upper_dir = pwd[pwd.length - 2]

if upper_dir != BASE_DIR or current_dir != UTIL_DIR then
  puts "error: gentags.rb must be executed on the utils directory"
  puts "hint: change directory to \"utils\" and then execute \"ruby gentags.rb\""
  exit
end

# Collect all tags in existing posts
Dir.glob("../_posts/*") do |file|
  File.open(file, "r") do |f|
    get_tags(f)
  end
end

# Remove duplication
$tags_in_posts.uniq!

n_generated = 0
$tags_in_posts.each do |tag|
  found = false

  # Chck if there is the tag page corresponding to tag
  Dir.glob("../tag/*") do |file|
    filename = File.basename(file, ".md")
    if filename == tag then
      found = true
      break
    end
  end
  
  # If there is no tagpage corresponding to the tag in
  # post, generate tag page.
  if !found then
    generate_tagpage(tag)
    n_generated += 1
  end
end

if n_generated == 0 then
  puts "Passed"
end
