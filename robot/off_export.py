"""Open Food Facts bulk export → products sold in Romania, in the shape their search API returned.
Written by the local model from tasks/local/off-export.md; one fix and review by Claude (2026-11-09)."""

def romania_rows(lines):
    """
    Generator that yields dicts representing Open Food Facts product rows for Romania only.
    
    Args:
        lines: Iterable of text lines (each may end with "\n").
        
    Yields:
        Dicts with keys: code, product_name, brands, quantity, nutrients, nutriscore_grade, 
        nova_group, ingredients_analysis_tags, allergens_tags, image_front_small_url.
    """
    lines = iter(lines)  # any iterable: a list in tests, the open export file in production
    try:
        header_line = next(lines)
    except StopIteration:
        return

    # Parse header to find column indices by name
    header_parts = header_line.rstrip('\r\n').split('\t')
    col_map = {}
    for idx, name in enumerate(header_parts):
        col_map[name] = idx
    
    # Define required nutrient keys
    nutrient_keys = [
        'energy-kcal_100g', 'fat_100g', 'saturated-fat_100g', 
        'carbohydrates_100g', 'sugars_100g', 'fiber_100g', 
        'proteins_100g', 'salt_100g'
    ]
    
    # Define specific column names for tags and image
    required_cols = [
        'code', 'product_name', 'quantity', 'brands', 'countries_tags',
        'allergens', 'nutriscore_grade', 'nova_group', 
        'ingredients_analysis_tags', 'image_small_url'
    ]
    
    # Check if all required columns exist in header
    for col in required_cols:
        if col not in col_map:
            return  # Skip if header is missing required columns

    # Process lines
    for line in lines:
        # Fast check before splitting
        if 'en:romania' not in line:
            continue
            
        # Remove trailing whitespace and split
        clean_line = line.rstrip('\r\n')
        parts = clean_line.split('\t')
        
        # Skip if fewer fields than header
        if len(parts) < len(header_parts):
            continue
        
        # Get column values by name
        try:
            code = parts[col_map['code']]
            product_name = parts[col_map['product_name']]
            brands = parts[col_map['brands']]
            quantity = parts[col_map['quantity']]
            countries_tags_text = parts[col_map['countries_tags']]
            nutriscore_grade = parts[col_map['nutriscore_grade']]
            nova_group_text = parts[col_map['nova_group']]
            ingredients_analysis_tags_text = parts[col_map['ingredients_analysis_tags']]
            image_small_url = parts[col_map['image_small_url']]
            
            # Check if en:romania is in countries_tags
            countries_tags_list = [t.strip() for t in countries_tags_text.split(',') if t.strip()]
            if 'en:romania' not in countries_tags_list:
                continue
            
            # Build nutrients dict
            nutrients = {}
            for key in nutrient_keys:
                if key not in col_map:  # a missing column means unknown, not a broken product
                    continue
                val_str = parts[col_map[key]]
                if val_str and val_str.strip():
                    try:
                        val = float(val_str)
                        nutrients[key] = val
                    except ValueError:
                        # Leave out if not a number
                        pass
            
            # Build nutriscore_grade
            grade = None
            if nutriscore_grade and nutriscore_grade.strip() in ['a', 'b', 'c', 'd', 'e']:
                grade = nutriscore_grade.strip()
            
            # Build nova_group
            nova = None
            if nova_group_text and nova_group_text.strip():
                try:
                    # Check if it's a whole number (int)
                    val = float(nova_group_text.strip())
                    if val == int(val):
                        nova = int(val)
                except ValueError:
                    pass
            
            # Build ingredients_analysis_tags
            tags_list = [t.strip() for t in ingredients_analysis_tags_text.split(',') if t.strip()]
            
            # Build allergens_tags
            allergens_list = [t.strip() for t in parts[col_map['allergens']].split(',') if t.strip()]
            
            yield {
                'code': code,
                'product_name': product_name,
                'brands': brands,
                'quantity': quantity,
                'nutriments': nutrients,
                'nutriscore_grade': grade,
                'nova_group': nova,
                'ingredients_analysis_tags': tags_list,
                'allergens_tags': allergens_list,
                'image_front_small_url': image_small_url if image_small_url and image_small_url.strip() else None
            }
        except (IndexError, KeyError):
            # Skip malformed lines
            continue
