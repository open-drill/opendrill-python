# Examples

`synthetic_borehole.json` is the same object as `opendrill.synthetic.SYNTHETIC_PAYLOAD`.

It is a made-up log for exercising the drawer: every hatch category, each strength symbol, an SPT row, lab rows with no SPT, a gap, a sheet boundary, a piezometer, and a supplied termination depth. The coordinates are 0. `SYN-CRS`, `SYN-H`, and `SYN-V` are labels typed into the file. They are not a coordinate reference system.

Render it:

```bash
opendrill render examples/synthetic_borehole.json --out synthetic.pdf
```
