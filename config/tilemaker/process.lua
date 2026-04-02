-- Minimal tilemaker process file placeholder.
-- Replace with a richer tile schema as needed.

function init_function()
end

function node_function(node)
end

function way_function(way)
  local highway = way:Find("highway")
  local building = way:Find("building")
  local waterway = way:Find("waterway")
  local natural = way:Find("natural")
  local landuse = way:Find("landuse")

  if building ~= "" then
    way:Layer("building", false)
    way:Attribute("building", building)
  end

  if highway ~= "" then
    way:Layer("transportation", false)
    way:Attribute("class", highway)
    way:MinZoom(8)
  end

  if waterway ~= "" then
    way:Layer("waterway", false)
    way:Attribute("class", waterway)
  end

  if natural == "water" then
    way:Layer("water", true)
  end

  if landuse ~= "" then
    way:Layer("landcover", true)
    way:Attribute("class", landuse)
  end
end

function relation_function(relation)
end
