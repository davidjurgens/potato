const p = class f {
  /**
   * Accept two comparable values and creates new instance of interval
   * Predicate Interval.comparable_less(low, high) supposed to return true on these values
   * @param low
   * @param high
   */
  constructor(t, e) {
    this.low = t, this.high = e;
  }
  /**
   * Clone interval
   * @returns {Interval}
   */
  clone() {
    return new f(this.low, this.high);
  }
  /**
   * Propery max returns clone of this interval
   * @returns {Interval}
   */
  get max() {
    return this.clone();
  }
  /**
   * Predicate returns true is this interval less than other interval
   * @param other_interval
   * @returns {boolean}
   */
  less_than(t) {
    return this.low < t.low || this.low === t.low && this.high < t.high;
  }
  /**
   * Predicate returns true is this interval equals to other interval
   * @param other_interval
   * @returns {boolean}
   */
  equal_to(t) {
    return this.low === t.low && this.high === t.high;
  }
  /**
   * Predicate returns true if this interval intersects other interval
   * @param other_interval
   * @returns {boolean}
   */
  intersect(t) {
    return !this.not_intersect(t);
  }
  /**
   * Predicate returns true if this interval does not intersect other interval
   * @param other_interval
   * @returns {boolean}
   */
  not_intersect(t) {
    return this.high < t.low || t.high < this.low;
  }
  /**
   * Returns new interval merged with other interval
   * @param {Interval} other_interval - Other interval to merge with
   * @returns {Interval}
   */
  merge(t) {
    return new f(
      this.low === void 0 ? t.low : this.low < t.low ? this.low : t.low,
      this.high === void 0 ? t.high : this.high > t.high ? this.high : t.high
    );
  }
  /**
   * Returns how key should return
   */
  output() {
    return [this.low, this.high];
  }
  /**
   * Function returns maximum between two comparable values
   * @param interval1
   * @param interval2
   * @returns {Interval}
   */
  static comparable_max(t, e) {
    return t.merge(e);
  }
  /**
   * Predicate returns true if first value less than second value
   * @param val1
   * @param val2
   * @returns {boolean}
   */
  static comparable_less_than(t, e) {
    return t < e;
  }
}, s = 0, l = 1;
class a {
  constructor(t = void 0, e = void 0, i = null, r = null, h = null, o = l) {
    if (this.left = i, this.right = r, this.parent = h, this.color = o, this.item = { key: t, value: e }, t && t instanceof Array && t.length === 2 && !Number.isNaN(t[0]) && !Number.isNaN(t[1])) {
      let [u, c] = t;
      u > c && ([u, c] = [c, u]), this.item.key = new p(u, c);
    }
    this.max = this.item.key ? this.item.key.max : void 0;
  }
  isNil() {
    return this.item.key === void 0 && this.item.value === void 0 && this.left === null && this.right === null && this.color === l;
  }
  _value_less_than(t) {
    return this.item.value && t.item.value && this.item.value.less_than ? this.item.value.less_than(t.item.value) : this.item.value < t.item.value;
  }
  less_than(t) {
    return this.item.value === this.item.key && t.item.value === t.item.key ? this.item.key.less_than(t.item.key) : this.item.key.less_than(t.item.key) || this.item.key.equal_to(t.item.key) && this._value_less_than(t);
  }
  _value_equal(t) {
    return this.item.value && t.item.value && this.item.value.equal_to ? this.item.value.equal_to(t.item.value) : this.item.value === t.item.value;
  }
  equal_to(t) {
    return this.item.value === this.item.key && t.item.value === t.item.key ? this.item.key.equal_to(t.item.key) : this.item.key.equal_to(t.item.key) && this._value_equal(t);
  }
  intersect(t) {
    return this.item.key.intersect(t.item.key);
  }
  copy_data(t) {
    this.item.key = t.item.key, this.item.value = t.item.value;
  }
  update_max() {
    if (this.max = this.item.key ? this.item.key.max : void 0, this.right && this.right.max) {
      const t = this.item.key.constructor.comparable_max;
      this.max = t(this.max, this.right.max);
    }
    if (this.left && this.left.max) {
      const t = this.item.key.constructor.comparable_max;
      this.max = t(this.max, this.left.max);
    }
  }
  // Other_node does not intersect any node of left subtree, if this.left.max < other_node.item.key.low
  not_intersect_left_subtree(t) {
    const e = this.item.key.constructor.comparable_less_than;
    let i = this.left.max.high !== void 0 ? this.left.max.high : this.left.max;
    return e(i, t.item.key.low);
  }
  // Other_node does not intersect right subtree if other_node.item.key.high < this.right.key.low
  not_intersect_right_subtree(t) {
    const e = this.item.key.constructor.comparable_less_than;
    let i = this.right.max.low !== void 0 ? this.right.max.low : this.right.item.key.low;
    return e(t.item.key.high, i);
  }
}
class m {
  /**
   * Construct new empty instance of IntervalTree
   */
  constructor() {
    this.root = null, this.nil_node = new a();
  }
  /**
   * Returns number of items stored in the interval tree
   * @returns {number}
   */
  get size() {
    let t = 0;
    return this.tree_walk(this.root, () => t++), t;
  }
  /**
   * Returns array of sorted keys in the ascending order
   * @returns {Array}
   */
  get keys() {
    let t = [];
    return this.tree_walk(this.root, (e) => t.push(
      e.item.key.output ? e.item.key.output() : e.item.key
    )), t;
  }
  /**
   * Return array of values in the ascending keys order
   * @returns {Array}
   */
  get values() {
    let t = [];
    return this.tree_walk(this.root, (e) => t.push(e.item.value)), t;
  }
  /**
   * Returns array of items (<key,value> pairs) in the ascended keys order
   * @returns {Array}
   */
  get items() {
    let t = [];
    return this.tree_walk(this.root, (e) => t.push({
      key: e.item.key.output ? e.item.key.output() : e.item.key,
      value: e.item.value
    })), t;
  }
  /**
   * Returns true if tree is empty
   * @returns {boolean}
   */
  isEmpty() {
    return this.root == null || this.root === this.nil_node;
  }
  /**
   * Clear tree
   */
  clear() {
    this.root = null;
  }
  /**
   * Insert new item into interval tree
   * @param {Interval} key - interval object or array of two numbers [low, high]
   * @param {any} value - value representing any object (optional)
   * @returns {Node} returns reference to inserted node as an object {key:interval, value: value}
   */
  insert(t, e = t) {
    if (t === void 0) return;
    let i = new a(t, e, this.nil_node, this.nil_node, null, s);
    return this.tree_insert(i), this.recalc_max(i), i;
  }
  /**
   * Returns true if item {key,value} exist in the tree
   * @param {Interval} key - interval correspondent to keys stored in the tree
   * @param {any} value - value object to be checked
   * @returns {boolean} true if item {key, value} exist in the tree, false otherwise
   */
  exist(t, e = t) {
    let i = new a(t, e);
    return !!this.tree_search(this.root, i);
  }
  /**
   * Remove entry {key, value} from the tree
   * @param {Interval} key - interval correspondent to keys stored in the tree
   * @param {any} value - value object
   * @returns {boolean} true if item {key, value} deleted, false if not found
   */
  remove(t, e = t) {
    let i = new a(t, e), r = this.tree_search(this.root, i);
    return r && this.tree_delete(r), r;
  }
  /**
   * Returns array of entry values which keys intersect with given interval <br/>
   * If no values stored in the tree, returns array of keys which intersect given interval
   * @param {Interval} interval - search interval, or tuple [low, high]
   * @param outputMapperFn(value,key) - optional function that maps (value, key) to custom output
   * @returns {Array}
   */
  search(t, e = (i, r) => i === r ? r.output() : i) {
    let i = new a(t), r = [];
    return this.tree_search_interval(this.root, i, r), r.map((h) => e(h.item.value, h.item.key));
  }
  /**
   * Returns true if intersection between given and any interval stored in the tree found
   * @param {Interval} interval - search interval or tuple [low, high]
   * @returns {boolean}
   */
  intersect_any(t) {
    let e = new a(t);
    return this.tree_find_any_interval(this.root, e);
  }
  /**
   * Tree visitor. For each node implement a callback function. <br/>
   * Method calls a callback function with two parameters (key, value)
   * @param visitor(key,value) - function to be called for each tree item
   */
  forEach(t) {
    this.tree_walk(this.root, (e) => t(e.item.key, e.item.value));
  }
  /**
   * Value Mapper. Walk through every node and map node value to another value
   * @param callback(value,key) - function to be called for each tree item
   */
  map(t) {
    const e = new m();
    return this.tree_walk(this.root, (i) => e.insert(i.item.key, t(i.item.value, i.item.key))), e;
  }
  /**
   * @param {Interval} interval - optional if the iterator is intended to start from the beginning
   * @param outputMapperFn(value,key) - optional function that maps (value, key) to custom output
   * @returns {Iterator}
   */
  *iterate(t, e = (i, r) => i === r ? r.output() : i) {
    let i;
    for (t ? i = this.tree_search_nearest_forward(this.root, new a(t)) : this.root && (i = this.local_minimum(this.root)); i; )
      yield e(i.item.value, i.item.key), i = this.tree_successor(i);
  }
  recalc_max(t) {
    let e = t;
    for (; e.parent != null; )
      e.parent.update_max(), e = e.parent;
  }
  tree_insert(t) {
    let e = this.root, i = null;
    if (this.root == null || this.root === this.nil_node)
      this.root = t;
    else {
      for (; e !== this.nil_node; )
        i = e, t.less_than(e) ? e = e.left : e = e.right;
      t.parent = i, t.less_than(i) ? i.left = t : i.right = t;
    }
    this.insert_fixup(t);
  }
  // After insertion insert_node may have red-colored parent, and this is a single possible violation
  // Go upwords to the root and re-color until violation will be resolved
  insert_fixup(t) {
    let e, i;
    for (e = t; e !== this.root && e.parent.color === s; )
      e.parent === e.parent.parent.left ? (i = e.parent.parent.right, i.color === s ? (e.parent.color = l, i.color = l, e.parent.parent.color = s, e = e.parent.parent) : (e === e.parent.right && (e = e.parent, this.rotate_left(e)), e.parent.color = l, e.parent.parent.color = s, this.rotate_right(e.parent.parent))) : (i = e.parent.parent.left, i.color === s ? (e.parent.color = l, i.color = l, e.parent.parent.color = s, e = e.parent.parent) : (e === e.parent.left && (e = e.parent, this.rotate_right(e)), e.parent.color = l, e.parent.parent.color = s, this.rotate_left(e.parent.parent)));
    this.root.color = l;
  }
  tree_delete(t) {
    let e, i;
    t.left === this.nil_node || t.right === this.nil_node ? e = t : e = this.tree_successor(t), e.left !== this.nil_node ? i = e.left : i = e.right, i.parent = e.parent, e === this.root ? this.root = i : (e === e.parent.left ? e.parent.left = i : e.parent.right = i, e.parent.update_max()), this.recalc_max(i), e !== t && (t.copy_data(e), t.update_max(), this.recalc_max(t)), /*fix_node != this.nil_node && */
    e.color === l && this.delete_fixup(i);
  }
  delete_fixup(t) {
    let e = t, i;
    for (; e !== this.root && e.parent != null && e.color === l; )
      e === e.parent.left ? (i = e.parent.right, i.color === s && (i.color = l, e.parent.color = s, this.rotate_left(e.parent), i = e.parent.right), i.left.color === l && i.right.color === l ? (i.color = s, e = e.parent) : (i.right.color === l && (i.color = s, i.left.color = l, this.rotate_right(i), i = e.parent.right), i.color = e.parent.color, e.parent.color = l, i.right.color = l, this.rotate_left(e.parent), e = this.root)) : (i = e.parent.left, i.color === s && (i.color = l, e.parent.color = s, this.rotate_right(e.parent), i = e.parent.left), i.left.color === l && i.right.color === l ? (i.color = s, e = e.parent) : (i.left.color === l && (i.color = s, i.right.color = l, this.rotate_left(i), i = e.parent.left), i.color = e.parent.color, e.parent.color = l, i.left.color = l, this.rotate_right(e.parent), e = this.root));
    e.color = l;
  }
  tree_search(t, e) {
    if (!(t == null || t === this.nil_node))
      return e.equal_to(t) ? t : e.less_than(t) ? this.tree_search(t.left, e) : this.tree_search(t.right, e);
  }
  tree_search_nearest_forward(t, e) {
    let i, r = t;
    for (; r && r !== this.nil_node; )
      r.less_than(e) ? r.intersect(e) ? (i = r, r = r.left) : r = r.right : ((!i || r.less_than(i)) && (i = r), r = r.left);
    return i || null;
  }
  // Original search_interval method; container res support push() insertion
  // Search all intervals intersecting given one
  tree_search_interval(t, e, i) {
    t != null && t !== this.nil_node && (t.left !== this.nil_node && !t.not_intersect_left_subtree(e) && this.tree_search_interval(t.left, e, i), t.intersect(e) && i.push(t), t.right !== this.nil_node && !t.not_intersect_right_subtree(e) && this.tree_search_interval(t.right, e, i));
  }
  tree_find_any_interval(t, e) {
    let i = !1;
    return t != null && t !== this.nil_node && (t.left !== this.nil_node && !t.not_intersect_left_subtree(e) && (i = this.tree_find_any_interval(t.left, e)), i || (i = t.intersect(e)), !i && t.right !== this.nil_node && !t.not_intersect_right_subtree(e) && (i = this.tree_find_any_interval(t.right, e))), i;
  }
  local_minimum(t) {
    let e = t;
    for (; e.left != null && e.left !== this.nil_node; )
      e = e.left;
    return e;
  }
  // not in use
  local_maximum(t) {
    let e = t;
    for (; e.right != null && e.right !== this.nil_node; )
      e = e.right;
    return e;
  }
  tree_successor(t) {
    let e, i, r;
    if (t.right !== this.nil_node)
      e = this.local_minimum(t.right);
    else {
      for (i = t, r = t.parent; r != null && r.right === i; )
        i = r, r = r.parent;
      e = r;
    }
    return e;
  }
  //           |            right-rotate(T,y)       |
  //           y            ---------------.       x
  //          / \                                  / \
  //         x   c          left-rotate(T,x)      a   y
  //        / \             <---------------         / \
  //       a   b                                    b   c
  rotate_left(t) {
    let e = t.right;
    t.right = e.left, e.left !== this.nil_node && (e.left.parent = t), e.parent = t.parent, t === this.root ? this.root = e : t === t.parent.left ? t.parent.left = e : t.parent.right = e, e.left = t, t.parent = e, t != null && t !== this.nil_node && t.update_max(), e = t.parent, e != null && e !== this.nil_node && e.update_max();
  }
  rotate_right(t) {
    let e = t.left;
    t.left = e.right, e.right !== this.nil_node && (e.right.parent = t), e.parent = t.parent, t === this.root ? this.root = e : t === t.parent.left ? t.parent.left = e : t.parent.right = e, e.right = t, t.parent = e, t !== null && t !== this.nil_node && t.update_max(), e = t.parent, e != null && e !== this.nil_node && e.update_max();
  }
  tree_walk(t, e) {
    t != null && t !== this.nil_node && (this.tree_walk(t.left, e), e(t), this.tree_walk(t.right, e));
  }
  /* Return true if all red nodes have exactly two black child nodes */
  testRedBlackProperty() {
    let t = !0;
    return this.tree_walk(this.root, function(e) {
      e.color === s && (e.left.color === l && e.right.color === l || (t = !1));
    }), t;
  }
  /* Throw error if not every path from root to bottom has same black height */
  testBlackHeightProperty(t) {
    let e = 0, i = 0, r = 0;
    if (t.color === l && e++, t.left !== this.nil_node ? i = this.testBlackHeightProperty(t.left) : i = 1, t.right !== this.nil_node ? r = this.testBlackHeightProperty(t.right) : r = 1, i !== r)
      throw new Error("Red-black height property violated");
    return e += i, e;
  }
}
function _(n) {
  const t = document.getElementById(n);
  if (t !== null)
    try {
      return JSON.parse(t.textContent);
    } catch (e) {
      console.warn(`could not parse json element '${n}'. Error: ${e}`);
    }
}
function g(n) {
  const t = document.getElementById("instance-text");
  if (t === null) {
    console.warn("cannot find instance text");
    return;
  }
  const e = t.textContent;
  if (!e || e === "") {
    console.log("text content in instance");
    return;
  }
  const i = new Set(n), r = e.split(" ");
  let h = "";
  for (const o in r)
    i.has(o) ? h += `
            <mark aria-hidden="true" class="emphasis">
                ${o}
            </mark>
            ` : h += o + " ";
  t.innerHTML = h;
}
function w(n) {
  console.log(n);
}
(function() {
  const n = _("emphasis");
  n !== void 0 && g(n);
  const t = _("suggestions");
  t !== void 0 && w(t);
})();
document.potato = {
  IntervalTree: m
};
