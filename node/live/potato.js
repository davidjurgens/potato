const H = class E {
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
    return new E(this.low, this.high);
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
    return new E(
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
}, g = 0, f = 1;
class x {
  constructor(t = void 0, e = void 0, r = null, n = null, l = null, a = f) {
    if (this.left = r, this.right = n, this.parent = l, this.color = a, this.item = { key: t, value: e }, t && t instanceof Array && t.length === 2 && !Number.isNaN(t[0]) && !Number.isNaN(t[1])) {
      let [s, o] = t;
      s > o && ([s, o] = [o, s]), this.item.key = new H(s, o);
    }
    this.max = this.item.key ? this.item.key.max : void 0;
  }
  isNil() {
    return this.item.key === void 0 && this.item.value === void 0 && this.left === null && this.right === null && this.color === f;
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
    let r = this.left.max.high !== void 0 ? this.left.max.high : this.left.max;
    return e(r, t.item.key.low);
  }
  // Other_node does not intersect right subtree if other_node.item.key.high < this.right.key.low
  not_intersect_right_subtree(t) {
    const e = this.item.key.constructor.comparable_less_than;
    let r = this.right.max.low !== void 0 ? this.right.max.low : this.right.item.key.low;
    return e(t.item.key.high, r);
  }
}
class F {
  /**
   * Construct new empty instance of IntervalTree
   */
  constructor() {
    this.root = null, this.nil_node = new x();
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
    let r = new x(t, e, this.nil_node, this.nil_node, null, g);
    return this.tree_insert(r), this.recalc_max(r), r;
  }
  /**
   * Returns true if item {key,value} exist in the tree
   * @param {Interval} key - interval correspondent to keys stored in the tree
   * @param {any} value - value object to be checked
   * @returns {boolean} true if item {key, value} exist in the tree, false otherwise
   */
  exist(t, e = t) {
    let r = new x(t, e);
    return !!this.tree_search(this.root, r);
  }
  /**
   * Remove entry {key, value} from the tree
   * @param {Interval} key - interval correspondent to keys stored in the tree
   * @param {any} value - value object
   * @returns {boolean} true if item {key, value} deleted, false if not found
   */
  remove(t, e = t) {
    let r = new x(t, e), n = this.tree_search(this.root, r);
    return n && this.tree_delete(n), n;
  }
  /**
   * Returns array of entry values which keys intersect with given interval <br/>
   * If no values stored in the tree, returns array of keys which intersect given interval
   * @param {Interval} interval - search interval, or tuple [low, high]
   * @param outputMapperFn(value,key) - optional function that maps (value, key) to custom output
   * @returns {Array}
   */
  search(t, e = (r, n) => r === n ? n.output() : r) {
    let r = new x(t), n = [];
    return this.tree_search_interval(this.root, r, n), n.map((l) => e(l.item.value, l.item.key));
  }
  /**
   * Returns true if intersection between given and any interval stored in the tree found
   * @param {Interval} interval - search interval or tuple [low, high]
   * @returns {boolean}
   */
  intersect_any(t) {
    let e = new x(t);
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
    const e = new F();
    return this.tree_walk(this.root, (r) => e.insert(r.item.key, t(r.item.value, r.item.key))), e;
  }
  /**
   * @param {Interval} interval - optional if the iterator is intended to start from the beginning
   * @param outputMapperFn(value,key) - optional function that maps (value, key) to custom output
   * @returns {Iterator}
   */
  *iterate(t, e = (r, n) => r === n ? n.output() : r) {
    let r;
    for (t ? r = this.tree_search_nearest_forward(this.root, new x(t)) : this.root && (r = this.local_minimum(this.root)); r; )
      yield e(r.item.value, r.item.key), r = this.tree_successor(r);
  }
  recalc_max(t) {
    let e = t;
    for (; e.parent != null; )
      e.parent.update_max(), e = e.parent;
  }
  tree_insert(t) {
    let e = this.root, r = null;
    if (this.root == null || this.root === this.nil_node)
      this.root = t;
    else {
      for (; e !== this.nil_node; )
        r = e, t.less_than(e) ? e = e.left : e = e.right;
      t.parent = r, t.less_than(r) ? r.left = t : r.right = t;
    }
    this.insert_fixup(t);
  }
  // After insertion insert_node may have red-colored parent, and this is a single possible violation
  // Go upwords to the root and re-color until violation will be resolved
  insert_fixup(t) {
    let e, r;
    for (e = t; e !== this.root && e.parent.color === g; )
      e.parent === e.parent.parent.left ? (r = e.parent.parent.right, r.color === g ? (e.parent.color = f, r.color = f, e.parent.parent.color = g, e = e.parent.parent) : (e === e.parent.right && (e = e.parent, this.rotate_left(e)), e.parent.color = f, e.parent.parent.color = g, this.rotate_right(e.parent.parent))) : (r = e.parent.parent.left, r.color === g ? (e.parent.color = f, r.color = f, e.parent.parent.color = g, e = e.parent.parent) : (e === e.parent.left && (e = e.parent, this.rotate_right(e)), e.parent.color = f, e.parent.parent.color = g, this.rotate_left(e.parent.parent)));
    this.root.color = f;
  }
  tree_delete(t) {
    let e, r;
    t.left === this.nil_node || t.right === this.nil_node ? e = t : e = this.tree_successor(t), e.left !== this.nil_node ? r = e.left : r = e.right, r.parent = e.parent, e === this.root ? this.root = r : (e === e.parent.left ? e.parent.left = r : e.parent.right = r, e.parent.update_max()), this.recalc_max(r), e !== t && (t.copy_data(e), t.update_max(), this.recalc_max(t)), /*fix_node != this.nil_node && */
    e.color === f && this.delete_fixup(r);
  }
  delete_fixup(t) {
    let e = t, r;
    for (; e !== this.root && e.parent != null && e.color === f; )
      e === e.parent.left ? (r = e.parent.right, r.color === g && (r.color = f, e.parent.color = g, this.rotate_left(e.parent), r = e.parent.right), r.left.color === f && r.right.color === f ? (r.color = g, e = e.parent) : (r.right.color === f && (r.color = g, r.left.color = f, this.rotate_right(r), r = e.parent.right), r.color = e.parent.color, e.parent.color = f, r.right.color = f, this.rotate_left(e.parent), e = this.root)) : (r = e.parent.left, r.color === g && (r.color = f, e.parent.color = g, this.rotate_right(e.parent), r = e.parent.left), r.left.color === f && r.right.color === f ? (r.color = g, e = e.parent) : (r.left.color === f && (r.color = g, r.right.color = f, this.rotate_left(r), r = e.parent.left), r.color = e.parent.color, e.parent.color = f, r.left.color = f, this.rotate_right(e.parent), e = this.root));
    e.color = f;
  }
  tree_search(t, e) {
    if (!(t == null || t === this.nil_node))
      return e.equal_to(t) ? t : e.less_than(t) ? this.tree_search(t.left, e) : this.tree_search(t.right, e);
  }
  tree_search_nearest_forward(t, e) {
    let r, n = t;
    for (; n && n !== this.nil_node; )
      n.less_than(e) ? n.intersect(e) ? (r = n, n = n.left) : n = n.right : ((!r || n.less_than(r)) && (r = n), n = n.left);
    return r || null;
  }
  // Original search_interval method; container res support push() insertion
  // Search all intervals intersecting given one
  tree_search_interval(t, e, r) {
    t != null && t !== this.nil_node && (t.left !== this.nil_node && !t.not_intersect_left_subtree(e) && this.tree_search_interval(t.left, e, r), t.intersect(e) && r.push(t), t.right !== this.nil_node && !t.not_intersect_right_subtree(e) && this.tree_search_interval(t.right, e, r));
  }
  tree_find_any_interval(t, e) {
    let r = !1;
    return t != null && t !== this.nil_node && (t.left !== this.nil_node && !t.not_intersect_left_subtree(e) && (r = this.tree_find_any_interval(t.left, e)), r || (r = t.intersect(e)), !r && t.right !== this.nil_node && !t.not_intersect_right_subtree(e) && (r = this.tree_find_any_interval(t.right, e))), r;
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
    let e, r, n;
    if (t.right !== this.nil_node)
      e = this.local_minimum(t.right);
    else {
      for (r = t, n = t.parent; n != null && n.right === r; )
        r = n, n = n.parent;
      e = n;
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
      e.color === g && (e.left.color === f && e.right.color === f || (t = !1));
    }), t;
  }
  /* Throw error if not every path from root to bottom has same black height */
  testBlackHeightProperty(t) {
    let e = 0, r = 0, n = 0;
    if (t.color === f && e++, t.left !== this.nil_node ? r = this.testBlackHeightProperty(t.left) : r = 1, t.right !== this.nil_node ? n = this.testBlackHeightProperty(t.right) : n = 1, r !== n)
      throw new Error("Red-black height property violated");
    return e += r, e;
  }
}
function N(i) {
  return i && i.__esModule && Object.prototype.hasOwnProperty.call(i, "default") ? i.default : i;
}
var k = { exports: {} }, b = { exports: {} };
(function(i, t) {
  (function(e) {
    t = e(), i.exports = t;
  })(function() {
    var e = function(s) {
      return s instanceof Function;
    }, r = function(s) {
      var o = Array.prototype.slice.call(arguments, 1);
      for (var c in o) {
        var h = o[c];
        if (typeof h == "object")
          for (var u in h)
            s[u] = h[u];
      }
      return s;
    }, n = {
      // internal object for indicating that class objects don't have a class object themselves,
      // may not be used by users
      _isClassObject: !1
    }, l = !1, a = function() {
    };
    return a._subClasses = [], a.prototype.init = function() {
    }, a._extend = function(s, o, c) {
      s === void 0 && (s = {}), o === void 0 && (o = {}), c === void 0 && (c = {}), c = r({}, n, c);
      var h = function() {
        l || (this._class = h, this.init instanceof Function && this.init.apply(this, arguments));
      }, u = this;
      l = !0;
      var d = new u();
      l = !1;
      var p = u.prototype;
      h.prototype = d, h.prototype.constructor = h, h._superClass = u, h._subClasses = [], u._subClasses.push(h), h._extend = u._extend, h._extends = function(C) {
        return this._superClass == a ? !1 : C == this._superClass || C == a ? !0 : this._superClass._extends(C);
      };
      for (var _ in s) {
        var m = Object.getOwnPropertyDescriptor(s, _), v = m.value;
        if (v !== null && typeof v == "object" && v.descriptor)
          Object.defineProperty(d, _, v);
        else if (!("value" in m) && ("set" in m || "get" in m))
          Object.defineProperty(d, _, m);
        else {
          d[_] = v;
          var O = p[_];
          e(v) && e(O) && v !== O && (v._super = O);
        }
      }
      if (!c._isClassObject) {
        var T = u._members === void 0 ? a : u._members._class, S = r({}, c, { _isClassObject: !0 }), R = T._extend(o, {}, S);
        R._instanceClass = h, h._members = new R();
      }
      return h;
    }, a._convert = function(s, o) {
      var c = s.prototype;
      return c.init = function() {
        var h = this._origin = a._construct(s, arguments);
        Object.keys(h).forEach(function(u) {
          h.hasOwnProperty(u) && Object.defineProperty(this, u, {
            get: function() {
              return h[u];
            }
          });
        }, this);
      }, a._extend(c, {}, o);
    }, a._construct = function(s, o) {
      o === void 0 && (o = []);
      var c = function() {
        return s.apply(this, o);
      };
      return c.prototype = s.prototype, new c();
    }, a._superDescriptor = function(s, o) {
      if ("_class" in s && s instanceof s._class && (s = s._class), "_extends" in s && s._extends instanceof Function && s._extends(this))
        return Object.getOwnPropertyDescriptor(s._superClass.prototype, o);
    }, a;
  });
})(b, b.exports);
var I = b.exports, D = I, w = D._extend({
  //-----------------------------------
  // Constructor
  //-----------------------------------
  init: function(i, t, e) {
    i = i instanceof Array ? i : [i], this._map = {}, this._list = [], this.callback = t, this.keyFields = i, this.isHashArray = !0, this.options = e || {
      ignoreDuplicates: !1
    }, t && t("construct");
  },
  //-----------------------------------
  // add()
  //-----------------------------------
  addOne: function(i) {
    var t = !1;
    for (var e in this.keyFields) {
      e = this.keyFields[e];
      var r = this.objectAt(i, e);
      if (r)
        if (this.has(r)) {
          if (this.options.ignoreDuplicates)
            return;
          if (this._map[r].indexOf(i) != -1) {
            t = !0;
            continue;
          }
          this._map[r].push(i);
        } else this._map[r] = [i];
    }
    (!t || this._list.indexOf(i) == -1) && this._list.push(i);
  },
  add: function() {
    for (var i = 0; i < arguments.length; i++)
      this.addOne(arguments[i]);
    return this.callback && this.callback("add", Array.prototype.slice.call(arguments, 0)), this;
  },
  addAll: function(i) {
    if (i.length < 100)
      this.add.apply(this, i);
    else
      for (var t = 0; t < i.length; t++)
        this.add(i[t]);
    return this;
  },
  addMap: function(i, t) {
    return this._map[i] = t, this.callback && this.callback("addMap", {
      key: i,
      obj: t
    }), this;
  },
  //-----------------------------------
  // Intersection, union, etc.
  //-----------------------------------
  /**
   * Returns a new HashArray that contains the intersection between this (A) and the hasharray passed in (B). Returns A ^ B.
   */
  intersection: function(i) {
    var t = this;
    if (!i || !i.isHashArray)
      throw Error("Cannot HashArray.intersection() on a non-hasharray object. You passed in: ", i);
    var e = this.clone(null, !0), r = this.clone(null, !0).addAll(this.all.concat(i.all));
    return r.all.forEach(function(n) {
      t.collides(n) && i.collides(n) && e.add(n);
    }), e;
  },
  /**
   * Returns a new HashArray that contains the complement (difference) between this hash array (A) and the hasharray passed in (B). Returns A - B.
   */
  complement: function(i) {
    if (!i || !i.isHashArray)
      throw Error("Cannot HashArray.complement() on a non-hasharray object. You passed in: ", i);
    var t = this.clone(null, !0);
    return this.all.forEach(function(e) {
      i.collides(e) || t.add(e);
    }), t;
  },
  //-----------------------------------
  // Retrieval
  //-----------------------------------
  get: function(i) {
    if (this.has(i))
      return !(this._map[i] instanceof Array) || this._map[i].length != 1 ? this._map[i] : this._map[i][0];
  },
  getAll: function(i) {
    if (i = i instanceof Array ? i : [i], i[0] == "*")
      return this.all;
    var t = new w(this.keyFields);
    for (var e in i)
      t.add.apply(t, this.getAsArray(i[e]));
    return t.all;
  },
  getAsArray: function(i) {
    return this._map[i] || [];
  },
  getUniqueRandomIntegers: function(i, t, e) {
    var r = [], n = {};
    for (i = Math.min(Math.max(e - t, 1), i); r.length < i; ) {
      var l = Math.floor(t + Math.random() * (e + 1));
      n[l] || (n[l] = !0, r.push(l));
    }
    return r;
  },
  sample: function(i, t) {
    var e = this.all, r = [];
    t && (e = this.getAll(t));
    for (var n = this.getUniqueRandomIntegers(i, 0, e.length - 1), l = 0; l < n.length; l++)
      r.push(e[n[l]]);
    return r;
  },
  //-----------------------------------
  // Peeking
  //-----------------------------------
  has: function(i) {
    return this._map.hasOwnProperty(i);
  },
  collides: function(i) {
    for (var t in this.keyFields)
      if (this.has(this.objectAt(i, this.keyFields[t])))
        return !0;
    return !1;
  },
  hasMultiple: function(i) {
    return this._map[i] instanceof Array;
  },
  //-----------------------------------
  // Removal
  //-----------------------------------
  removeByKey: function() {
    for (var i = [], t = 0; t < arguments.length; t++) {
      var e = arguments[t], r = this._map[e].concat();
      if (r) {
        i = i.concat(r);
        for (var n in r) {
          var l = r[n];
          for (var a in this.keyFields) {
            var s = this.objectAt(l, this.keyFields[a]);
            if (s && this.has(s)) {
              var a = this._map[s].indexOf(l);
              a != -1 && this._map[s].splice(a, 1), this._map[s].length == 0 && delete this._map[s];
            }
          }
          this._list.splice(this._list.indexOf(l), 1);
        }
      }
      delete this._map[e];
    }
    return this.callback && this.callback("removeByKey", i), this;
  },
  remove: function() {
    for (var i = 0; i < arguments.length; i++) {
      var t = arguments[i];
      for (var r in this.keyFields) {
        var e = this.objectAt(t, this.keyFields[r]);
        if (e) {
          var r = this._map[e].indexOf(t);
          if (r != -1)
            this._map[e].splice(r, 1);
          else
            throw new Error("HashArray: attempting to remove an object that was never added!" + e);
          this._map[e].length == 0 && delete this._map[e];
        }
      }
      var r = this._list.indexOf(t);
      if (r != -1)
        this._list.splice(r, 1);
      else
        throw new Error("HashArray: attempting to remove an object that was never added!" + e);
    }
    return this.callback && this.callback("remove", arguments), this;
  },
  removeAll: function() {
    var i = this._list.concat();
    return this._map = {}, this._list = [], this.callback && this.callback("remove", i), this;
  },
  //-----------------------------------
  // Utility
  //-----------------------------------
  objectAt: function(i, t) {
    if (typeof t == "string")
      return i[t];
    for (var e = t.concat(); e.length && i; )
      i = i[e.shift()];
    return i;
  },
  //-----------------------------------
  // Iteration
  //-----------------------------------
  forEach: function(i, t) {
    i = i instanceof Array ? i : [i];
    var e = this.getAll(i);
    return e.forEach(t), this;
  },
  forEachDeep: function(i, t, e) {
    i = i instanceof Array ? i : [i];
    var r = this, n = this.getAll(i);
    return n.forEach(function(l) {
      e(r.objectAt(l, t), l);
    }), this;
  },
  //-----------------------------------
  // Cloning
  //-----------------------------------
  clone: function(i, t) {
    var e = new w(this.keyFields.concat(), i || this.callback);
    return t || e.add.apply(e, this.all.concat()), e;
  },
  //-----------------------------------
  // Mathematical
  //-----------------------------------
  sum: function(i, t, e) {
    var r = this, n = 0;
    return this.forEachDeep(i, t, function(l, a) {
      e !== void 0 && (l *= r.objectAt(a, e)), n += l;
    }), n;
  },
  average: function(i, t, e) {
    var r = 0, n = 0, l = 0, a = this;
    return e !== void 0 && this.forEachDeep(i, e, function(s) {
      l += s;
    }), this.forEachDeep(i, t, function(s, o) {
      e !== void 0 && (s *= a.objectAt(o, e) / l), r += s, n++;
    }), e !== void 0 ? r : r / n;
  },
  //-----------------------------------
  // Filtering
  //-----------------------------------
  filter: function(i, t) {
    var e = this, r = typeof t == "function" ? t : l, n = new w(this.keyFields);
    return n.addAll(this.getAll(i).filter(r)), n;
    function l(a) {
      var s = e.objectAt(a, t);
      return s !== void 0 && s !== !1;
    }
  }
});
Object.defineProperty(w.prototype, "all", {
  get: function() {
    return this._list;
  }
});
Object.defineProperty(w.prototype, "map", {
  get: function() {
    return this._map;
  }
});
var q = w;
typeof window < "u" && (window.HashArray = w);
var B = q, y = B, L = 64, P = /^[\s]*$/, $ = [
  {
    regex: /[åäàáâãæ]/ig,
    alternate: "a"
  },
  {
    regex: /[èéêë]/ig,
    alternate: "e"
  },
  {
    regex: /[ìíîï]/ig,
    alternate: "i"
  },
  {
    regex: /[òóôõö]/ig,
    alternate: "o"
  },
  {
    regex: /[ùúûü]/ig,
    alternate: "u"
  },
  {
    regex: /[æ]/ig,
    alternate: "ae"
  }
];
String.prototype.replaceCharAt = function(i, t) {
  return this.substr(0, i) + t + this.substr(i + t.length);
};
var A = function(i, t) {
  this.options = t || {}, this.options.ignoreCase = this.options.ignoreCase === void 0 ? !0 : this.options.ignoreCase, this.options.maxCacheSize = this.options.maxCacheSize || L, this.options.cache = this.options.hasOwnProperty("cache") ? this.options.cache : !0, this.options.splitOnRegEx = this.options.hasOwnProperty("splitOnRegEx") ? this.options.splitOnRegEx : /\s/g, this.options.splitOnGetRegEx = this.options.hasOwnProperty("splitOnGetRegEx") ? this.options.splitOnGetRegEx : this.options.splitOnRegEx, this.options.min = this.options.min || 1, this.options.keepAll = this.options.hasOwnProperty("keepAll") ? this.options.keepAll : !1, this.options.keepAllKey = this.options.hasOwnProperty("keepAllKey") ? this.options.keepAllKey : "id", this.options.idFieldOrFunction = this.options.hasOwnProperty("idFieldOrFunction") ? this.options.idFieldOrFunction : void 0, this.options.expandRegexes = this.options.expandRegexes || $, this.options.insertFullUnsplitKey = this.options.hasOwnProperty("insertFullUnsplitKey") ? this.options.insertFullUnsplitKey : !1, this.keyFields = i ? i instanceof Array ? i : [i] : [], this.root = {}, this.size = 0, this.options.cache && (this.getCache = new y("key"));
};
function j(i, t) {
  return t.length === 1 ? i[t[0]] : j(i[t[0]], t.slice(1, t.length));
}
A.prototype = {
  add: function(i, t) {
    this.options.cache && this.clearCache(), typeof t == "number" && (t = void 0);
    var e = t || this.keyFields;
    for (var r in e) {
      var n = e[r], l = n instanceof Array, a = l ? j(i, n) : i[n];
      if (a) {
        a = a.toString();
        for (var s = this.expandString(a), o = 0; o < s.length; o++) {
          var c = s[o];
          this.map(c, i);
        }
      }
    }
  },
  /**
   * By default using the options.expandRegexes, given a string like 'ö är bra', this will expand it to:
   *
   * ['ö är bra', 'o är bra', 'ö ar bra', 'o ar bra']
   *
   * By default this was built to allow for internationalization, but it could be also be expanded to
   * allow for word alternates, etc. like spelling alternates ('teh' and 'the').
   *
   * This is used for insertion! This should not be used for lookup since if a person explicitly types
   * 'ä' they probably do not want to see all results for 'a'.
   *
   * @param value The string to find alternates for.
   * @returns {Array} Always returns an array even if no matches.
   */
  expandString: function(i) {
    var t = [i];
    if (this.options.expandRegexes && this.options.expandRegexes.length)
      for (var e = 0; e < this.options.expandRegexes.length; e++)
        for (var r = this.options.expandRegexes[e], n; (n = r.regex.exec(i)) !== null; ) {
          var l = i.replaceCharAt(n.index, r.alternate);
          t.push(l);
        }
    return t;
  },
  addAll: function(i, t) {
    for (var e = 0; e < i.length; e++)
      this.add(i[e], t);
  },
  reset: function() {
    this.root = {}, this.size = 0;
  },
  clearCache: function() {
    this.getCache = new y("key");
  },
  cleanCache: function() {
    for (; this.getCache.all.length > this.options.maxCacheSize; )
      this.getCache.remove(this.getCache.all[0]);
  },
  addFromObject: function(i, t) {
    this.options.cache && this.clearCache(), t = t || "value", this.keyFields.indexOf("_key_") == -1 && this.keyFields.push("_key_");
    for (var e in i) {
      var r = { _key_: e };
      r[t] = i[e], this.add(r);
    }
  },
  map: function(i, t) {
    if (this.options.splitOnRegEx && this.options.splitOnRegEx.test(i)) {
      var e = i.split(this.options.splitOnRegEx), r = e.filter(function(u) {
        return P.test(u);
      }), n = e.filter(function(u) {
        return u === i;
      }), l = n.length + r.length === e.length;
      if (!l) {
        for (var a = 0, s = e.length; a < s; a++)
          P.test(e[a]) || this.map(e[a], t);
        if (!this.options.insertFullUnsplitKey)
          return;
      }
    }
    this.options.cache && this.clearCache(), this.options.keepAll && (this.indexed = this.indexed || new y([this.options.keepAllKey]), this.indexed.add(t)), this.options.ignoreCase && (i = i.toLowerCase());
    var o = this.keyToArr(i), c = this;
    h(o, t, this.root);
    function h(u, d, p) {
      if (u.length == 0) {
        p.value = p.value || [], p.value.push(d);
        return;
      }
      var _ = u.shift();
      p[_] || c.size++, p[_] = p[_] || {}, h(u, d, p[_]);
    }
  },
  keyToArr: function(i) {
    var t;
    if (this.options.min && this.options.min > 1) {
      if (i.length < this.options.min)
        return [];
      t = [i.substr(0, this.options.min)], t = t.concat(i.substr(this.options.min).split(""));
    } else t = i.split("");
    return t;
  },
  findNode: function(i) {
    return t(this.keyToArr(i), this.root);
    function t(e, r) {
      if (r) {
        if (e.length == 0) return r;
        var n = e.shift();
        return t(e, r[n]);
      }
    }
  },
  _getCacheKey: function(i, t) {
    var e = i;
    return t && (e = i + "_" + t), e;
  },
  _get: function(i, t) {
    i = this.options.ignoreCase ? i.toLowerCase() : i;
    var e, r;
    if (this.options.cache && (e = this.getCache.get(this._getCacheKey(i, t))))
      return e.value;
    for (var n = void 0, l = this.options.indexField ? [this.options.indexField] : this.keyFields, a = this.options.splitOnGetRegEx ? i.split(this.options.splitOnGetRegEx) : [i], s = 0, o = a.length; s < o; s++)
      if (!(this.options.min && a[s].length < this.options.min)) {
        var c = new y(l);
        (r = this.findNode(a[s])) && d(r, c), n = n ? n.intersection(c) : c;
      }
    var h = n ? n.all : [];
    if (this.options.cache) {
      var u = this._getCacheKey(i, t);
      this.getCache.add({ key: u, value: h }), this.cleanCache();
    }
    return h;
    function d(p, _) {
      if (!(t && _.all.length === t)) {
        if (p.value && p.value.length)
          if (!t || _.all.length + p.value.length < t)
            _.addAll(p.value);
          else {
            _.addAll(p.value.slice(0, t - _.all.length));
            return;
          }
        for (var m in p) {
          if (t && _.all.length === t)
            return;
          m != "value" && d(p[m], _);
        }
      }
    }
  },
  get: function(i, t, e) {
    var r = this.options.indexField ? [this.options.indexField] : this.keyFields, n = void 0, l = void 0;
    if (t && !this.options.idFieldOrFunction)
      throw new Error("To use the accumulator, you must specify and idFieldOrFunction");
    i = i instanceof Array ? i : [i];
    for (var a = 0, s = i.length; a < s; a++) {
      var o = this._get(i[a], e);
      t ? l = t(l, i[a], o, this) : n = n ? n.addAll(o) : new y(r).addAll(o);
    }
    return t ? l : n.all;
  },
  search: function(i, t, e) {
    return this.get(i, t, e);
  },
  getId: function(i) {
    return typeof this.options.idFieldOrFunction == "function" ? this.options.idFieldOrFunction(i) : i[this.options.idFieldOrFunction];
  }
};
A.UNION_REDUCER = function(i, t, e, r) {
  if (i === void 0)
    return e;
  var n = {}, l, a, s = Math.max(i.length, e.length), o = [], c = 0;
  for (l = 0; l < s; l++)
    l < i.length && (a = r.getId(i[l]), n[a] = n[a] ? n[a] : 0, n[a]++, n[a] === 2 && (o[c++] = i[l])), l < e.length && (a = r.getId(e[l]), n[a] = n[a] ? n[a] : 0, n[a]++, n[a] === 2 && (o[c++] = e[l]));
  return o;
};
k.exports = A;
k.exports.default = A;
var z = k.exports, U = z;
const K = /* @__PURE__ */ N(U);
(function() {
  function i(l) {
    const a = document.getElementById(l);
    if (a !== null)
      try {
        return JSON.parse(a.textContent);
      } catch (s) {
        console.warn(`could not parse json element '${l}'. Error: ${s}`);
      }
  }
  function t(l) {
    const a = document.getElementById("instance-text");
    if (a === null) {
      console.warn("cannot find instance text");
      return;
    }
    const s = a.textContent;
    if (!s || s === "") {
      console.log("text content in instance");
      return;
    }
    console.log(s);
    const o = new K();
    l.map((p) => o.map(p, p));
    const c = s.split(" ");
    let h = !1, u = "", d = "";
    for (const p of c) {
      const _ = u + p, m = o.search(_);
      if (m.length === 0 && h) {
        d += `
                <mark aria-hidden="true" class="emphasis">${u}</mark>                 
                `, d += p, u = "", h = !1;
        continue;
      }
      if (m.length === 0) {
        d += p + " ", u = "";
        continue;
      }
      if (m.length === 1) {
        d += `
                <mark aria-hidden="true" class="emphasis">${_}</mark>              
                `, u = "", h = !1;
        continue;
      }
      m.includes(_) && (h = !0), u = _ + " ";
    }
    a.innerHTML = d;
  }
  function e(l) {
    console.log(l);
  }
  const r = i("emphasis");
  r !== void 0 && (console.log(r), t(r));
  const n = i("suggestions");
  n !== void 0 && e(n);
})();
document.potato = {
  IntervalTree: F
};
