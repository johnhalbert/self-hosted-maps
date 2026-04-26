-- Conservative repo-owned Tilemaker profile.
-- It preserves OpenMapTiles-style layer names used by the viewer and emits a
-- small allowlisted set of additive thematic layers without raw tag pass-through.

local green_landuse = {
  allotments = true,
  cemetery = true,
  forest = true,
  grass = true,
  meadow = true,
  orchard = true,
  recreation_ground = true,
  village_green = true,
  vineyard = true
}

local green_natural = {
  grassland = true,
  heath = true,
  scrub = true,
  tree = true,
  tree_row = true,
  wood = true
}

local park_leisure = {
  dog_park = true,
  garden = true,
  nature_reserve = true,
  park = true,
  playground = true,
  recreation_ground = true
}

local mobility_highway = {
  bridleway = true,
  cycleway = true,
  footway = true,
  path = true,
  pedestrian = true,
  steps = true,
  track = true
}

local amenity_theme = {
  arts_centre = { "civic_poi", "arts_centre" },
  bar = { "food_drink", "bar" },
  cafe = { "food_drink", "cafe" },
  clinic = { "health", "clinic" },
  college = { "education", "college" },
  community_centre = { "public_services", "community_centre" },
  doctors = { "health", "doctors" },
  drinking_water = { "public_services", "drinking_water" },
  fast_food = { "food_drink", "fast_food" },
  fire_station = { "public_services", "fire_station" },
  food_court = { "food_drink", "food_court" },
  hospital = { "health", "hospital" },
  kindergarten = { "education", "kindergarten" },
  library = { "public_services", "library" },
  pharmacy = { "health", "pharmacy" },
  police = { "public_services", "police" },
  post_office = { "public_services", "post_office" },
  pub = { "food_drink", "pub" },
  restaurant = { "food_drink", "restaurant" },
  school = { "education", "school" },
  shelter = { "public_services", "shelter" },
  social_facility = { "public_services", "social_facility" },
  theatre = { "civic_poi", "theatre" },
  toilets = { "public_services", "toilets" },
  townhall = { "public_services", "townhall" },
  university = { "education", "university" }
}

local tourism_theme = {
  attraction = { "tourism", "attraction" },
  camp_site = { "tourism", "camp_site" },
  gallery = { "tourism", "gallery" },
  hotel = { "tourism", "hotel" },
  information = { "tourism", "information" },
  museum = { "tourism", "museum" },
  viewpoint = { "tourism", "viewpoint" }
}

local leisure_theme = {
  fitness_centre = { "recreation", "fitness_centre" },
  marina = { "recreation", "marina" },
  pitch = { "recreation", "pitch" },
  playground = { "recreation", "playground" },
  sports_centre = { "recreation", "sports_centre" },
  swimming_pool = { "recreation", "swimming_pool" }
}

local function copy_attr(object, key, out_key)
  local value = object:Find(key)
  if value ~= "" then
    object:Attribute(out_key or key, value)
  end
end

local function copy_name(object)
  local name = object:Find("name")
  if name ~= "" then
    object:Attribute("name", name)
    object:Attribute("name:latin", name)
  end
end

local function add_theme_attrs(object, theme, class, subclass)
  object:Attribute("theme", theme)
  object:Attribute("class", class)
  if subclass ~= nil and subclass ~= "" then
    object:Attribute("subclass", subclass)
  end
  copy_name(object)
  copy_attr(object, "brand")
  copy_attr(object, "operator")
  copy_attr(object, "network")
  copy_attr(object, "ref")
  copy_attr(object, "access")
  copy_attr(object, "opening_hours")
  copy_attr(object, "wheelchair")
end

local function emit_theme_poi(object, spec, class, subclass)
  object:Layer("theme_poi", false)
  object:MinZoom(14)
  add_theme_attrs(object, spec[1], class, subclass or spec[2])
end

local function emit_green_area(object, class)
  object:Layer("theme_area", true)
  object:MinZoom(10)
  add_theme_attrs(object, "green_space", class, object:Find(class))
end

local function emit_named_line(object, layer, class)
  local name = object:Find("name")
  local ref = object:Find("ref")
  if name ~= "" or ref ~= "" then
    object:Layer(layer, false)
    object:MinZoom(10)
    if name ~= "" then
      object:Attribute("name", name)
      object:Attribute("name:latin", name)
    end
    if ref ~= "" then
      object:Attribute("ref", ref)
    end
    object:Attribute("class", class)
  end
end

function init_function()
end

function node_function(node)
  local place = node:Find("place")
  if place ~= "" then
    node:Layer("place", false)
    node:MinZoom(4)
    node:Attribute("class", place)
    copy_name(node)
  end

  local amenity = node:Find("amenity")
  if amenity_theme[amenity] then
    emit_theme_poi(node, amenity_theme[amenity], amenity, amenity)
    node:Layer("poi", false)
    node:MinZoom(14)
    node:Attribute("class", amenity)
    copy_name(node)
    return
  end

  local tourism = node:Find("tourism")
  if tourism_theme[tourism] then
    emit_theme_poi(node, tourism_theme[tourism], tourism, tourism)
    return
  end

  local leisure = node:Find("leisure")
  if leisure_theme[leisure] then
    emit_theme_poi(node, leisure_theme[leisure], leisure, leisure)
  end
end

function way_function(way)
  local highway = way:Find("highway")
  local building = way:Find("building")
  local waterway = way:Find("waterway")
  local natural = way:Find("natural")
  local landuse = way:Find("landuse")
  local leisure = way:Find("leisure")
  local boundary = way:Find("boundary")

  if building ~= "" then
    way:Layer("building", false)
    way:MinZoom(13)
    way:Attribute("building", building)
  end

  if highway ~= "" then
    way:Layer("transportation", false)
    way:Attribute("class", highway)
    way:MinZoom(8)
    emit_named_line(way, "transportation_name", highway)
    if mobility_highway[highway] then
      way:Layer("theme_line", false)
      way:MinZoom(11)
      add_theme_attrs(way, "mobility", highway, highway)
    end
  end

  if waterway ~= "" then
    way:Layer("waterway", false)
    way:Attribute("class", waterway)
    emit_named_line(way, "water_name", waterway)
  end

  if natural == "water" then
    way:Layer("water", true)
    emit_named_line(way, "water_name", "water")
  end

  if green_landuse[landuse] or green_natural[natural] then
    way:Layer("landcover", true)
    way:Attribute("class", landuse ~= "" and landuse or natural)
  end

  if green_landuse[landuse] then
    way:Layer("landuse", true)
    way:Attribute("class", landuse)
    emit_green_area(way, "landuse")
  end

  if park_leisure[leisure] then
    way:Layer("park", true)
    way:Attribute("class", leisure)
    emit_green_area(way, "leisure")
  elseif leisure_theme[leisure] then
    way:Layer("theme_area", true)
    way:MinZoom(13)
    add_theme_attrs(way, leisure_theme[leisure][1], leisure, leisure)
  end

  if boundary == "administrative" then
    way:Layer("boundary", false)
    way:MinZoom(4)
    way:Attribute("class", boundary)
    copy_attr(way, "admin_level")
  end
end

function relation_function(relation)
  local boundary = relation:Find("boundary")
  local natural = relation:Find("natural")
  local landuse = relation:Find("landuse")
  local leisure = relation:Find("leisure")

  if boundary == "administrative" then
    relation:Layer("boundary", false)
    relation:MinZoom(4)
    relation:Attribute("class", boundary)
    copy_attr(relation, "admin_level")
  end

  if natural == "water" then
    relation:Layer("water", true)
    emit_named_line(relation, "water_name", "water")
  end

  if green_landuse[landuse] then
    relation:Layer("landcover", true)
    relation:Attribute("class", landuse)
    relation:Layer("landuse", true)
    relation:Attribute("class", landuse)
    emit_green_area(relation, "landuse")
  end

  if park_leisure[leisure] then
    relation:Layer("park", true)
    relation:Attribute("class", leisure)
    emit_green_area(relation, "leisure")
  end
end
